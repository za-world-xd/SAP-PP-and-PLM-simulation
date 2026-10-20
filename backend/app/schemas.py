from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Qty = Annotated[Decimal, Field(gt=0, le=1000000, max_digits=14, decimal_places=4)]
Nonnegative = Annotated[Decimal, Field(ge=0, le=100000000, max_digits=16, decimal_places=4)]
Code = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialInput(Schema):
    matnr: Code
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["FERT", "HALB", "ROH"]
    unit: Literal["EA", "L"] = "EA"
    procurement: Literal["E", "F"]
    safety: Nonnegative = Decimal(0)
    lead_days: int = Field(default=1, ge=0, le=365)
    lot_rule: Literal["LFL", "FIXED", "MIN"] = "LFL"
    lot_qty: Qty = Decimal(1)
    cost: Nonnegative = Decimal(10)


class Component(Schema):
    component: Code
    qty: Qty


class BomInput(Schema):
    matnr: Code
    revision: str = Field(min_length=1, max_length=20)
    valid_from: date
    components: list[Component] = Field(min_length=1, max_length=100)


class WorkCenterInput(Schema):
    arbpl: Code
    name: str = Field(min_length=1, max_length=120)
    units_per_shift: int = Field(gt=0, le=100000)
    shift_minutes: int = Field(default=480, gt=0, le=1440)
    rate: Nonnegative = Decimal(2)


class OperationInput(Schema):
    op: str = Field(pattern=r"^\d{4}$")
    center: Code
    description: str = Field(min_length=1, max_length=120)
    setup: Nonnegative
    run: Nonnegative


class RoutingInput(Schema):
    matnr: Code
    operations: list[OperationInput] = Field(min_length=1, max_length=50)


class DemandInput(Schema):
    matnr: Code = "EB-1000"
    qty: Qty
    due: date
    source: str = Field(default="SD demo demand", min_length=1, max_length=120)


class RunInput(Schema):
    planning_date: date


class ConvertInput(Schema):
    proposal_id: int = Field(gt=0)


class PostingInput(Schema):
    key: str = Field(min_length=8, max_length=100)


class ReceiptInput(PostingInput):
    qty: Qty


class ConfirmationInput(PostingInput):
    op: str
    yield_qty: Nonnegative
    scrap: Nonnegative = Decimal(0)
    minutes: Nonnegative
    final: bool = True


class ChangeInput(BomInput):
    reason: str = Field(min_length=5, max_length=1000)


class ChangeStatus(Schema):
    target: Literal["Approved", "Released", "Implemented"]


class ResetInput(Schema):
    fixture: Literal["demo", "zero"] = "demo"
    confirmation: Literal["RESET DEMO DATA"]

