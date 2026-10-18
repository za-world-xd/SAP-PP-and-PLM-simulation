from decimal import Decimal

from sqlalchemy import select

from ..models import Bom, Material, ProductionOrder, Proposal, Reservation, Routing, WorkCenter
from .bom import items
from .common import emit, get, quantity, record, require
from .inventory import move


def convert(db, proposal_id):
    proposal = get(db, Proposal, proposal_id)
    require(proposal.kind == "MAKE" and proposal.status == "Open", "Only an open make proposal can be converted")
    bom = get(db, Bom, proposal.bom_id)
    require(bom.status == "Released", "Proposal BOM is no longer released; replan")
    routes = db.scalars(select(Routing).where(Routing.matnr == proposal.matnr).order_by(Routing.op)).all()
    require(bool(routes), "Maintain routing before converting this material")
    components = [{"matnr": i.component, "qty": str(i.qty * proposal.qty), "rate": str(get(db, Material, i.component).cost)} for i in items(db, bom.id)]
    operations = [{"op": r.op, "center": r.center, "description": r.description,
                   "setup": str(r.setup), "run": str(r.run), "rate": str(get(db, WorkCenter, r.center).rate),
                   "yield": "0", "scrap": "0", "minutes": "0", "final": False} for r in routes]
    planned = sum(Decimal(c["qty"]) * Decimal(c["rate"]) for c in components)
    planned += sum((r.setup + r.run * proposal.qty) * get(db, WorkCenter, r.center).rate for r in routes)
    order = ProductionOrder(proposal_id=proposal.id, matnr=proposal.matnr, qty=proposal.qty, start=proposal.start, due=proposal.due,
                            bom_id=bom.id, components=components, operations=operations, planned_cost=planned)
    db.add(order)
    proposal.status = "Converted"
    db.flush()
    emit(db, "PP", f"ORD-{order.id}", f"Production order created with frozen BOM {bom.revision} and routing")
    return record(order)


def release(db, order_id):
    order = get(db, ProductionOrder, order_id)
    require(order.status == "CRTD", "Only a created order can be released")
    for component in order.components:
        db.add(Reservation(order_id=order.id, matnr=component["matnr"], required=Decimal(component["qty"])))
    order.status = "REL"
    emit(db, "MM", f"ORD-{order.id}", "Component reservations created; no physical inventory consumed")
    return record(order)


def issue(db, order_id):
    order = get(db, ProductionOrder, order_id)
    require(order.status in ("REL", "PCNF"), "Order must be released before component issue")
    reservations = db.scalars(select(Reservation).where(Reservation.order_id == order.id)).all()
    outstanding = [r for r in reservations if r.required > r.issued]
    require(bool(outstanding), "All components have already been issued")
    costs = {c["matnr"]: Decimal(c["rate"]) for c in order.components}
    for reservation in outstanding:
        qty = reservation.required - reservation.issued
        move(db, reservation.matnr, -qty, "261", f"ORD-{order.id}")
        reservation.issued += qty
        order.actual_cost += qty * costs[reservation.matnr]
    emit(db, "MM / FI", f"ORD-{order.id}", "Components issued (261); inventory reduced, simulated material cost charged to order")
    return record(order)


def confirm(db, order_id, op, yield_qty, scrap, minutes, final):
    order = get(db, ProductionOrder, order_id)
    require(order.status in ("REL", "PCNF"), "Only a released or partially confirmed order accepts confirmations")
    require(not db.scalar(select(Reservation.id).where(Reservation.order_id == order.id, Reservation.issued < Reservation.required)), "Issue all reserved components first")
    operations = [dict(o) for o in order.operations]
    index = next((i for i, operation in enumerate(operations) if operation["op"] == op), None)
    require(index is not None, "Operation not found", 404)
    operation = operations[index]
    require(not operation["final"], "Operation already finally confirmed")
    require(all(o["final"] for o in operations[:index]), "Complete preceding operations first")
    for amount in (yield_qty, scrap):
        if amount:
            quantity(db, order.matnr, amount)
    processed = Decimal(operation["yield"]) + Decimal(operation["scrap"]) + yield_qty + scrap
    limit = Decimal(operations[index - 1]["yield"]) if index else order.qty
    require(yield_qty + scrap > 0 or (final and processed == limit),
            "A zero-quantity confirmation can only finalize fully accounted operation input")
    require(processed <= limit, "Confirmation exceeds available operation input")
    require(not final or processed == limit, "Final confirmation must account for all available units as yield or scrap")
    operation["yield"] = str(Decimal(operation["yield"]) + yield_qty)
    operation["scrap"] = str(Decimal(operation["scrap"]) + scrap)
    operation["minutes"] = str(Decimal(operation["minutes"]) + minutes)
    operation["final"] = final
    order.operations = operations
    order.actual_cost += minutes * Decimal(operation["rate"])
    order.status = "CNF" if all(o["final"] for o in operations) else "PCNF"
    emit(db, "CO", f"ORD-{order.id}", f"Operation {op}: yield {yield_qty}, scrap {scrap}, {minutes} minutes; simulated activity cost recorded")
    if index == len(operations) - 1 and final and operation["center"] == "WC-TEST":
        emit(db, "QM", f"ORD-{order.id}", "Final test complete; simulated inspection notification (no quality-stock processing)")
    return record(order)


def receipt(db, order_id, qty):
    order = get(db, ProductionOrder, order_id)
    require(order.status in ("PCNF", "CNF"), "Order has no receivable confirmed output")
    quantity(db, order.matnr, qty)
    confirmed = Decimal(order.operations[-1]["yield"])
    require(order.received + qty <= confirmed, "Receipt exceeds unreceived final-operation yield")
    require(order.received + qty <= order.qty, "Receipt exceeds order quantity")
    move(db, order.matnr, qty, "101", f"ORD-{order.id}")
    order.received += qty
    if order.received == order.qty:
        require(all(o["final"] for o in order.operations), "Final confirmations required for full delivery")
        order.status = "DLV"
    emit(db, "MM / FI", f"ORD-{order.id}", f"Goods receipt (101): {qty} into stock; simulated inventory valuation, no WIP settlement")
    return record(order)


def complete(db, order_id):
    order = get(db, ProductionOrder, order_id)
    require(order.status == "DLV", "Only a fully delivered order can be technically completed")
    require(not db.scalar(select(Reservation.id).where(Reservation.order_id == order.id, Reservation.issued < Reservation.required)), "Open reservations remain")
    order.status = "TECO"
    emit(db, "PP", f"ORD-{order.id}", "Technically complete; further postings blocked")
    return record(order)


def purchase_receipt(db, proposal_id, qty):
    proposal = get(db, Proposal, proposal_id)
    require(proposal.kind == "BUY" and proposal.status in ("Open", "Committed"), "Only an outstanding purchase requisition can be received")
    quantity(db, proposal.matnr, qty)
    require(proposal.received + qty <= proposal.qty, "Receipt exceeds purchase requisition quantity")
    move(db, proposal.matnr, qty, "101-PR", f"PR-{proposal.id}")
    proposal.received += qty
    proposal.status = "Received" if proposal.received == proposal.qty else "Committed"
    emit(db, "MM", f"PR-{proposal.id}", f"Simplified external receipt: {qty} {proposal.matnr}; PO processing omitted")
    return record(proposal)
