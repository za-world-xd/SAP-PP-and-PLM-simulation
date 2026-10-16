from decimal import Decimal

from sqlalchemy import select

from ..models import Bom, BomItem, Material
from .common import get, record, require


def selected(db, matnr, valid_on):
    bom = db.scalar(select(Bom).where(Bom.matnr == matnr, Bom.status == "Released", Bom.valid_from <= valid_on)
                    .order_by(Bom.valid_from.desc()))
    require(bom is not None, f"No released BOM for {matnr} on {valid_on}")
    return bom


def items(db, bom_id):
    return db.scalars(select(BomItem).where(BomItem.bom_id == bom_id).order_by(BomItem.id)).all()


def tree(db, matnr, valid_on, path=(), multiplier=Decimal(1)):
    require(matnr not in path, f"BOM cycle: {' > '.join((*path, matnr))}", 422)
    material = get(db, Material, matnr)
    result = {"matnr": matnr, "name": material.name, "unit": material.unit, "qty": float(multiplier), "children": []}
    if material.procurement == "E":
        bom = selected(db, matnr, valid_on)
        result.update(bom_id=bom.id, revision=bom.revision, valid_from=bom.valid_from)
        result["children"] = [tree(db, i.component, valid_on, (*path, matnr), multiplier * i.qty) for i in items(db, bom.id)]
    return result


def validate_graph(db):
    # Check the union of revisions so a future revision cannot introduce recursion.
    graph = {}
    for bom in db.scalars(select(Bom)).all():
        graph.setdefault(bom.matnr, set()).update(i.component for i in items(db, bom.id))
    visiting, visited = set(), set()

    def visit(code):
        require(code not in visiting, f"BOM cycle involving {code}", 422)
        if code in visited:
            return
        visiting.add(code)
        for child in graph.get(code, ()):
            visit(child)
        visiting.remove(code)
        visited.add(code)

    for code in graph:
        visit(code)
    return graph


def create_bom(db, matnr, revision, valid_from, components, status="Draft"):
    material = get(db, Material, matnr)
    require(material.procurement == "E", "BOM parent must be an in-house material", 422)
    require(bool(components), "BOM must contain components", 422)
    require(len({c["component"] for c in components}) == len(components), "Duplicate BOM component", 422)
    require(not db.scalar(select(Bom).where(Bom.matnr == matnr, Bom.valid_from == valid_from)), "A BOM already starts on this date")
    bom = Bom(matnr=matnr, revision=revision, valid_from=valid_from, status=status)
    db.add(bom)
    db.flush()
    for component in components:
        child = get(db, Material, component["component"])
        qty = Decimal(str(component["qty"]))
        require(qty > 0 and (child.unit == "L" or qty == qty.to_integral_value()), "Invalid component quantity", 422)
        db.add(BomItem(bom_id=bom.id, component=child.matnr, qty=qty))
    db.flush()
    validate_graph(db)
    return record(bom)
