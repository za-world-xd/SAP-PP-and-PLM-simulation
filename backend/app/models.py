from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Material(Base):
    __tablename__ = "MARA"
    __table_args__ = (
        CheckConstraint("stock >= 0 AND safety >= 0 AND lead_days >= 0 AND lot_qty > 0 AND cost >= 0"),
        CheckConstraint("procurement IN ('E', 'F') AND lot_rule IN ('LFL', 'FIXED', 'MIN')"),
    )
    matnr: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    kind: Mapped[str]
    unit: Mapped[str]
    procurement: Mapped[str]
    stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    safety: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    lead_days: Mapped[int] = mapped_column(default=1)
    lot_rule: Mapped[str] = mapped_column(default="LFL")
    lot_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=1)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=10)


class WorkCenter(Base):
    __tablename__ = "CRHD"
    __table_args__ = (CheckConstraint("shift_minutes > 0 AND rate >= 0"),)
    arbpl: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    units_per_shift: Mapped[int]
    shift_minutes: Mapped[int] = mapped_column(default=480)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=2)


class Routing(Base):
    __tablename__ = "PLPO"
    __table_args__ = (UniqueConstraint("matnr", "op"), CheckConstraint("setup >= 0 AND run >= 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    op: Mapped[str]
    center: Mapped[str] = mapped_column(ForeignKey("CRHD.arbpl"))
    description: Mapped[str]
    setup: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    run: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class Bom(Base):
    __tablename__ = "STKO"
    __table_args__ = (UniqueConstraint("matnr", "valid_from"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    revision: Mapped[str]
    valid_from: Mapped[str]
    status: Mapped[str] = mapped_column(default="Released")
    change_id: Mapped[str | None]


class BomItem(Base):
    __tablename__ = "STPO"
    __table_args__ = (UniqueConstraint("bom_id", "component"), CheckConstraint("qty > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("STKO.id"))
    component: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class Requirement(Base):
    __tablename__ = "DEMAND"
    id: Mapped[int] = mapped_column(primary_key=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    due: Mapped[str]
    source: Mapped[str] = mapped_column(default="SD demo demand")


class MrpRun(Base):
    __tablename__ = "MRP_RUN"
    id: Mapped[int] = mapped_column(primary_key=True)
    created: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    inputs: Mapped[dict] = mapped_column(JSON)
    rows: Mapped[list] = mapped_column(JSON)
    exceptions: Mapped[list] = mapped_column(JSON)


class Proposal(Base):
    __tablename__ = "PLAF_EBAN"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("MRP_RUN.id"))
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    received: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    kind: Mapped[str]
    start: Mapped[str]
    due: Mapped[str]
    status: Mapped[str] = mapped_column(default="Open")
    bom_id: Mapped[int | None] = mapped_column(ForeignKey("STKO.id"))


class ProductionOrder(Base):
    __tablename__ = "AFKO"
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("PLAF_EBAN.id"), unique=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    received: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str] = mapped_column(default="CRTD")
    start: Mapped[str]
    due: Mapped[str]
    bom_id: Mapped[int] = mapped_column(ForeignKey("STKO.id"))
    components: Mapped[list] = mapped_column(JSON)
    operations: Mapped[list] = mapped_column(JSON)
    planned_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)


class Reservation(Base):
    __tablename__ = "RESB"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("AFKO.id"))
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    required: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    issued: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)


class Movement(Base):
    __tablename__ = "STOCK_MOVEMENT"
    id: Mapped[int] = mapped_column(primary_key=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    kind: Mapped[str]
    reference: Mapped[str]
    created: Mapped[str]


class Posting(Base):
    __tablename__ = "POSTING"
    key: Mapped[str] = mapped_column(primary_key=True)
    fingerprint: Mapped[str]
    result: Mapped[dict] = mapped_column(JSON)


class Change(Base):
    __tablename__ = "AENR"
    id: Mapped[int] = mapped_column(primary_key=True)
    matnr: Mapped[str] = mapped_column(ForeignKey("MARA.matnr"))
    reason: Mapped[str]
    valid_from: Mapped[str]
    status: Mapped[str] = mapped_column(default="Requested")
    bom_id: Mapped[int] = mapped_column(ForeignKey("STKO.id"))
    history: Mapped[list] = mapped_column(JSON)


class IntegrationEvent(Base):
    __tablename__ = "INTEGRATION_EVENT"
    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str]
    reference: Mapped[str]
    message: Mapped[str]
    created: Mapped[str]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

