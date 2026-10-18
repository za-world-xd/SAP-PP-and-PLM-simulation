from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import select

from ..models import Material, MrpRun, ProductionOrder, Proposal, Requirement, Reservation, now
from .bom import items, selected, validate_graph
from .common import emit, require


def lot(material, shortfall):
    if material.lot_rule == "FIXED":
        return (shortfall / material.lot_qty).to_integral_value(rounding=ROUND_CEILING) * material.lot_qty
    if material.lot_rule == "MIN":
        return max(shortfall, material.lot_qty)
    return shortfall


def run(db, planning_date):
    materials = {m.matnr: m for m in db.scalars(select(Material)).all()}
    demands = db.scalars(select(Requirement)).all()
    require(bool(demands), "Create an independent requirement before running MRP", 422)
    graph = validate_graph(db)
    indegree = {code: 0 for code in materials}
    for children in graph.values():
        for code in children:
            indegree[code] += 1
    ready = sorted(code for code, degree in indegree.items() if degree == 0)
    sequence = []
    while ready:
        parent = ready.pop(0)
        sequence.append(parent)
        for child in sorted(graph.get(parent, ())):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    require(len(sequence) == len(materials), "BOM contains a cycle", 422)

    requirements = defaultdict(lambda: defaultdict(Decimal))
    receipts = defaultdict(lambda: defaultdict(Decimal))
    for demand in demands:
        requirements[demand.matnr][demand.due] += demand.qty
    orders = db.scalars(select(ProductionOrder).where(ProductionOrder.status != "TECO")).all()
    for order in orders:
        receipts[order.matnr][order.due] += order.qty - order.received
        if order.status == "CRTD":
            for component in order.components:
                requirements[component["matnr"]][order.start] += Decimal(component["qty"])
        else:
            for reservation in db.scalars(select(Reservation).where(Reservation.order_id == order.id)).all():
                requirements[reservation.matnr][order.start] += reservation.required - reservation.issued
    for proposal in db.scalars(select(Proposal).where(Proposal.status == "Committed", Proposal.kind == "BUY")).all():
        receipts[proposal.matnr][proposal.due] += proposal.qty - proposal.received

    for previous in db.scalars(select(MrpRun).where(MrpRun.active)).all():
        previous.active = False
    for proposal in db.scalars(select(Proposal).where(Proposal.status == "Open")).all():
        proposal.status = "Superseded"
    run_record = MrpRun(created=now(), inputs={"planning_date": planning_date, "stock": {k: str(v.stock) for k, v in materials.items()},
                                             "demands": [{"id": d.id, "matnr": d.matnr, "qty": str(d.qty), "due": d.due} for d in demands]},
                        rows=[], exceptions=[])
    db.add(run_record)
    db.flush()
    rows, exceptions = [], []
    for code in sequence:
        material = materials[code]
        available = material.stock
        dates = sorted(set(requirements[code]) | set(receipts[code]))
        if not dates:
            continue
        rows.append({"matnr": code, "date": planning_date, "type": "Opening stock", "gross": 0, "supply": float(available), "projected": float(available)})
        for due in dates:
            gross, scheduled = requirements[code][due], receipts[code][due]
            available += scheduled
            shortfall = max(Decimal(0), gross + material.safety - available)
            planned = lot(material, shortfall) if shortfall else Decimal(0)
            if planned:
                start = (date.fromisoformat(due) - timedelta(days=material.lead_days)).isoformat()
                bom = selected(db, code, start) if material.procurement == "E" else None
                proposal = Proposal(run_id=run_record.id, matnr=code, qty=planned,
                                    kind="MAKE" if bom else "BUY", start=start, due=due, bom_id=bom.id if bom else None)
                db.add(proposal)
                db.flush()
                if start < planning_date:
                    exceptions.append({"matnr": code, "proposal_id": proposal.id, "message": f"Required start {start} precedes planning date {planning_date}"})
                if bom:
                    for component in items(db, bom.id):
                        requirements[component.component][start] += planned * component.qty
                else:
                    emit(db, "MM", f"PR-{proposal.id}", f"Purchase requisition for {planned} {material.unit} {code}; receipt {due}")
            before_supply = available - gross
            available += planned - gross
            rows.append({"matnr": code, "date": due, "type": "Requirements / supply", "gross": float(gross),
                         "scheduled": float(scheduled), "shortfall": float(shortfall), "supply": float(planned),
                         "before_supply": float(before_supply), "projected": float(available)})
    run_record.rows, run_record.exceptions = rows, exceptions
    emit(db, "PP", f"MRP-{run_record.id}", "MRP completed; proposals replace previous unconverted proposals. Physical stock unchanged.")
    return run_record

