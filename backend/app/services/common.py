from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import inspect

from ..models import IntegrationEvent, now


def require(condition, message, status=409):
    if not condition:
        raise HTTPException(status, message)


def get(db, model, key):
    obj = db.get(model, key)
    require(obj is not None, f"{model.__tablename__} {key} not found", 404)
    return obj


def record(obj):
    return {column.key: float(value) if isinstance(value := getattr(obj, column.key), Decimal) else value
            for column in inspect(obj).mapper.column_attrs}


def emit(db, module, reference, message):
    db.add(IntegrationEvent(module=module, reference=reference, message=message, created=now()))


def quantity(db, material, qty):
    from ..models import Material
    mat = get(db, Material, material)
    require(qty > 0, "Quantity must be positive", 422)
    require(mat.unit == "L" or qty == qty.to_integral_value(), "EA quantities must be whole numbers", 422)
    require(qty == qty.quantize(Decimal("0.0001")), "Maximum quantity precision is four decimal places", 422)
    return mat

