import os
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import schemas as s
from .database import Base, SessionLocal, engine, session
from .models import (Bom, BomItem, Change, IntegrationEvent, Material, Movement, MrpRun,
                     ProductionOrder, Proposal, Requirement, Reservation, Routing, WorkCenter)
from .seed import seed
from .services import bom, changes, mrp, orders
from .services.common import emit, get, quantity, record, require
from .services.inventory import post_once


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        seed(db)
    yield


app = FastAPI(title="E-Bike PP + PLM Simulator", version="0.1.0", lifespan=lifespan)


@app.exception_handler(IntegrityError)
async def integrity_error(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "Duplicate identifier or invalid data reference; no changes saved"})


DB = Depends(session)


def listing(db, model):
    return [record(row) for row in db.scalars(select(model)).all()]


@app.get("/api/health")
def health():
    return {"status": "ok", "application": "E-Bike PP + PLM Simulator"}


@app.get("/api/materials")
def materials(db: Session = DB):
    return listing(db, Material)


@app.get("/api/materials/{matnr}")
def material(matnr: str, db: Session = DB):
    return record(get(db, Material, matnr))


def validate_material(data):
    require(data.unit == "L" or (data.safety == data.safety.to_integral_value() and data.lot_qty == data.lot_qty.to_integral_value()), "EA safety stock and lot size must be whole numbers", 422)


@app.post("/api/materials", status_code=201)
def create_material(data: s.MaterialInput, db: Session = DB):
    validate_material(data)
    require(not db.get(Material, data.matnr), "Material already exists")
    obj = Material(**data.model_dump(), stock=0)
    db.add(obj)
    db.flush()
    return record(obj)


@app.put("/api/materials/{matnr}")
def update_material(matnr: str, data: s.MaterialInput, db: Session = DB):
    obj = get(db, Material, matnr)
    require(matnr == data.matnr, "Material code cannot be changed", 422)
    require(obj.unit == data.unit and obj.procurement == data.procurement, "Unit and procurement type are fixed after creation")
    validate_material(data)
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    return record(obj)


@app.get("/api/work-centers")
def centers(db: Session = DB):
    return listing(db, WorkCenter)


@app.post("/api/work-centers", status_code=201)
def create_center(data: s.WorkCenterInput, db: Session = DB):
    require(not db.get(WorkCenter, data.arbpl), "Work center already exists")
    obj = WorkCenter(**data.model_dump())
    db.add(obj)
    db.flush()
    return record(obj)


@app.put("/api/work-centers/{arbpl}")
def update_center(arbpl: str, data: s.WorkCenterInput, db: Session = DB):
    require(data.arbpl == arbpl, "Work center code cannot change", 422)
    obj = get(db, WorkCenter, arbpl)
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    return record(obj)


@app.get("/api/routing/{matnr}")
def routing(matnr: str, db: Session = DB):
    get(db, Material, matnr)
    return [record(r) for r in db.scalars(select(Routing).where(Routing.matnr == matnr).order_by(Routing.op)).all()]


@app.put("/api/routing/{matnr}")
def save_routing(matnr: str, data: s.RoutingInput, db: Session = DB):
    require(matnr == data.matnr, "Material code mismatch", 422)
    require(get(db, Material, matnr).procurement == "E", "Routing requires an in-house material", 422)
    require(len({o.op for o in data.operations}) == len(data.operations), "Duplicate operation", 422)
    for operation in data.operations:
        get(db, WorkCenter, operation.center)
    db.execute(delete(Routing).where(Routing.matnr == matnr))
    for operation in data.operations:
        db.add(Routing(matnr=matnr, **operation.model_dump()))
    db.flush()
    return routing(matnr, db)


@app.get("/api/bom/{matnr}")
def read_bom(matnr: str, valid_on: date, db: Session = DB):
    return bom.tree(db, matnr, valid_on.isoformat())


@app.get("/api/bom-revisions")
def revisions(db: Session = DB):
    return [{**record(b), "components": [record(i) for i in bom.items(db, b.id)]} for b in db.scalars(select(Bom)).all()]


@app.post("/api/bom", status_code=201)
def initial_bom(data: s.BomInput, db: Session = DB):
    require(not db.scalar(select(Bom).where(Bom.matnr == data.matnr)), "Use engineering change management to revise an existing BOM")
    return bom.create_bom(db, data.matnr, data.revision, data.valid_from.isoformat(), [c.model_dump() for c in data.components], "Released")


@app.get("/api/requirements")
def requirements(db: Session = DB):
    return listing(db, Requirement)


@app.post("/api/requirements", status_code=201)
def create_requirement(data: s.DemandInput, db: Session = DB):
    quantity(db, data.matnr, data.qty)
    obj = Requirement(**{**data.model_dump(), "due": data.due.isoformat()})
    db.add(obj)
    db.flush()
    emit(db, "SD", f"DEMAND-{obj.id}", f"Independent requirement: {obj.qty} {obj.matnr} by {obj.due}; simulated demand input")
    return record(obj)


@app.post("/api/mrp/run")
def run_mrp(data: s.RunInput, db: Session = DB):
    result = mrp.run(db, data.planning_date.isoformat())
    return record(result)


@app.get("/api/mrp/runs")
def runs(db: Session = DB):
    return listing(db, MrpRun)


@app.get("/api/mrp/runs/{run_id}")
def read_run(run_id: int, db: Session = DB):
    return record(get(db, MrpRun, run_id))


@app.get("/api/mrp/proposals")
def proposals(db: Session = DB):
    return listing(db, Proposal)


@app.get("/api/stock-requirements/{matnr}")
def stock_requirements(matnr: str, db: Session = DB):
    material = get(db, Material, matnr)
    run = db.scalar(select(MrpRun).where(MrpRun.active))
    return {"material": record(material), "run_id": run.id if run else None,
            "rows": [r for r in run.rows if r["matnr"] == matnr] if run else []}


@app.get("/api/orders")
def read_orders(db: Session = DB):
    return listing(db, ProductionOrder)


@app.get("/api/orders/{order_id}")
def read_order(order_id: int, db: Session = DB):
    return {**record(get(db, ProductionOrder, order_id)),
            "reservations": [record(r) for r in db.scalars(select(Reservation).where(Reservation.order_id == order_id)).all()]}


@app.post("/api/orders/convert", status_code=201)
def convert(data: s.ConvertInput, db: Session = DB):
    return orders.convert(db, data.proposal_id)


def posting(db, data, action, callback):
    return post_once(db, data.key, action, data.model_dump(mode="json", exclude={"key"}), callback)


@app.post("/api/orders/{order_id}/release")
def release(order_id: int, data: s.PostingInput, db: Session = DB):
    return posting(db, data, f"release:{order_id}", lambda: orders.release(db, order_id))


@app.post("/api/orders/{order_id}/goods-issue")
def issue(order_id: int, data: s.PostingInput, db: Session = DB):
    return posting(db, data, f"issue:{order_id}", lambda: orders.issue(db, order_id))


@app.post("/api/orders/{order_id}/confirm")
def confirm(order_id: int, data: s.ConfirmationInput, db: Session = DB):
    return posting(db, data, f"confirm:{order_id}", lambda: orders.confirm(db, order_id, data.op, data.yield_qty, data.scrap, data.minutes, data.final))


@app.post("/api/orders/{order_id}/goods-receipt")
def receipt(order_id: int, data: s.ReceiptInput, db: Session = DB):
    return posting(db, data, f"receipt:{order_id}", lambda: orders.receipt(db, order_id, data.qty))


@app.post("/api/orders/{order_id}/complete")
def complete(order_id: int, data: s.PostingInput, db: Session = DB):
    return posting(db, data, f"complete:{order_id}", lambda: orders.complete(db, order_id))


@app.post("/api/purchase-requisitions/{proposal_id}/goods-receipt")
def external_receipt(proposal_id: int, data: s.ReceiptInput, db: Session = DB):
    return posting(db, data, f"pr-receipt:{proposal_id}", lambda: orders.purchase_receipt(db, proposal_id, data.qty))


@app.get("/api/ecn")
def read_changes(db: Session = DB):
    return listing(db, Change)


@app.post("/api/ecn", status_code=201)
def create_change(data: s.ChangeInput, db: Session = DB):
    return changes.create(db, data.matnr, data.reason, data.valid_from.isoformat(), data.revision, [c.model_dump() for c in data.components])


@app.post("/api/ecn/{change_id}/status")
def change_status(change_id: int, data: s.ChangeStatus, db: Session = DB):
    return changes.transition(db, change_id, data.target)


@app.get("/api/ecn/{change_id}/impact")
def change_impact(change_id: int, db: Session = DB):
    return changes.impact(db, change_id)


@app.get("/api/events")
def events(db: Session = DB):
    return [record(e) for e in db.scalars(select(IntegrationEvent).order_by(IntegrationEvent.id.desc()).limit(250)).all()]


@app.get("/api/movements")
def movements(db: Session = DB):
    return listing(db, Movement)


@app.get("/api/dashboard")
def dashboard(db: Session = DB):
    counts = dict(db.execute(select(ProductionOrder.status, func.count()).group_by(ProductionOrder.status)).all())
    latest = db.scalar(select(MrpRun).where(MrpRun.active))
    shortages = [r for r in latest.rows if r.get("shortfall", 0) > 0] if latest else []
    loads = defaultdict(Decimal)
    for order in db.scalars(select(ProductionOrder).where(ProductionOrder.status.notin_(["DLV", "TECO"]))).all():
        for op in order.operations:
            if not op["final"]:
                remaining = max(Decimal(0), order.qty - Decimal(op["yield"]) - Decimal(op["scrap"]))
                loads[op["center"]] += Decimal(op["run"]) * remaining + (Decimal(op["setup"]) if Decimal(op["minutes"]) == 0 else 0)
    capacity = [{**record(w), "load_minutes": float(loads[w.arbpl]), "shifts_required": round(float(loads[w.arbpl]) / w.shift_minutes, 2)} for w in db.scalars(select(WorkCenter)).all()]
    return {"orders_by_status": counts, "open_proposals": db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "Open")),
            "shortages": shortages, "exceptions": latest.exceptions if latest else [], "capacity": capacity,
            "recent_changes": listing(db, Change)[-5:], "demo_reset_enabled": os.getenv("ENABLE_DEMO_RESET", "1") == "1"}


@app.post("/api/demo/reset")
def reset(data: s.ResetInput, db: Session = DB):
    require(os.getenv("ENABLE_DEMO_RESET", "1") == "1", "Demo reset is disabled", 403)
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.flush()
    db.expunge_all()
    seed(db, data.fixture)
    return {"status": "reset", "fixture": data.fixture}


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if (DIST / "index.html").is_file():
        return FileResponse(DIST / "index.html")
    return {"message": "API is running. Build frontend with npm run build in frontend/, then restart backend.", "docs": "/docs"}

