import hashlib
import json
from decimal import Decimal

from ..models import Material, Movement, Posting, now
from .common import get, require


def move(db, matnr, qty, kind, reference):
    material = get(db, Material, matnr)
    qty = Decimal(str(qty))
    require(material.stock + qty >= 0, f"Insufficient stock of {matnr}: available {material.stock}, issue {-qty}")
    material.stock += qty
    db.add(Movement(matnr=matnr, qty=qty, kind=kind, reference=reference, created=now()))


def post_once(db, key, action, payload, operation):
    fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True, default=str).encode()).hexdigest()
    previous = db.get(Posting, key)
    if previous:
        require(previous.fingerprint == fingerprint, "Posting key already used for a different request")
        return previous.result
    result = operation()
    db.add(Posting(key=key, fingerprint=fingerprint, result=result))
    return result

