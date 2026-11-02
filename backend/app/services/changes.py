from sqlalchemy import select

from ..models import Bom, Change, ProductionOrder, Proposal, now
from .bom import create_bom, items
from .common import emit, get, record, require


def create(db, matnr, reason, valid_from, revision, components):
    bom = create_bom(db, matnr, revision, valid_from, components)
    change = Change(matnr=matnr, reason=reason, valid_from=valid_from, bom_id=bom["id"],
                    history=[{"status": "Requested", "at": now()}])
    db.add(change)
    db.flush()
    get(db, Bom, change.bom_id).change_id = f"ECN-{change.id}"
    return record(change)


def transition(db, change_id, target):
    change = get(db, Change, change_id)
    allowed = {"Requested": "Approved", "Approved": "Released", "Released": "Implemented"}
    require(allowed.get(change.status) == target, f"Cannot move change from {change.status} to {target}")
    if target == "Released":
        get(db, Bom, change.bom_id).status = "Released"
    if target == "Implemented":
        require(change.valid_from <= now()[:10], "Effectivity date has not arrived")
        require(bool(db.scalar(select(ProductionOrder.id).where(ProductionOrder.bom_id == change.bom_id))), "Create an order using this revision before recording implementation")
    change.status = target
    change.history = [*change.history, {"status": target, "at": now()}]
    emit(db, "PLM", f"ECN-{change.id}", f"Engineering change {target.lower()}: {change.reason}")
    return record(change)


def impact(db, change_id):
    change = get(db, Change, change_id)

    def contains(bom_id, target, valid_on, seen=()):
        bom = get(db, Bom, bom_id)
        if bom.matnr == target:
            return True
        if bom.matnr in seen:
            return False
        for component in items(db, bom_id):
            if component.component == target:
                return True
            child = db.scalar(select(Bom).where(Bom.matnr == component.component, Bom.status == "Released", Bom.valid_from <= valid_on).order_by(Bom.valid_from.desc()))
            if child and contains(child.id, target, valid_on, (*seen, bom.matnr)):
                return True
        return False

    affected = []
    for proposal in db.scalars(select(Proposal).where(Proposal.status == "Open", Proposal.kind == "MAKE")).all():
        if contains(proposal.bom_id, change.matnr, proposal.start):
            affected.append({"type": "Planned order", "id": proposal.id, "matnr": proposal.matnr, "status": proposal.status,
                             "start": proposal.start, "effectivity_relevant": proposal.start >= change.valid_from,
                             "action": "Replan to apply eligible revision"})
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.status != "TECO")).all():
        if contains(order.bom_id, change.matnr, order.start):
            affected.append({"type": "Production order", "id": order.id, "matnr": order.matnr, "status": order.status,
                             "start": order.start, "effectivity_relevant": order.start >= change.valid_from,
                             "action": "Review; copied components remain frozen"})
    return affected
