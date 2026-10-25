from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bom, BomItem, Material, ProductionOrder, Proposal
from app.seed import seed
from app.services.inventory import move


def post(client, path, payload=None, expected=200):
    response = client.post(f"/api{path}", json=payload or {})
    assert response.status_code == expected, response.text
    return response.json()


def demand(client, qty=200, matnr="EB-1000", due="2026-12-02"):
    return post(client, "/requirements", {"matnr": matnr, "qty": qty, "due": due}, 201)


def plan(client):
    return post(client, "/mrp/run", {"planning_date": "2026-11-02"})


def proposals(client, status="Open"):
    return [p for p in client.get("/api/mrp/proposals").json() if p["status"] == status]


def keyed(client, path, **payload):
    return post(client, path, {"key": str(uuid4()), **payload})


def finish(client, order):
    oid = order["id"]
    keyed(client, f"/orders/{oid}/release")
    keyed(client, f"/orders/{oid}/goods-issue")
    for op in order["operations"]:
        keyed(client, f"/orders/{oid}/confirm", op=op["op"], yield_qty=order["qty"], scrap=0,
              minutes=float(op["setup"]) + float(op["run"]) * order["qty"], final=True)
    keyed(client, f"/orders/{oid}/goods-receipt", qty=order["qty"])
    return keyed(client, f"/orders/{oid}/complete")


def change(client, valid_from="2026-11-10"):
    return post(client, "/ecn", {"matnr": "PU-400", "revision": "B", "valid_from": valid_from,
                                "reason": "Upgrade controller thermal performance",
                                "components": [{"component": "MT-401", "qty": 1}, {"component": "BP-402", "qty": 1}, {"component": "CT-404", "qty": 1}]}, 201)


def test_seed_is_repeatable_and_all_make_materials_have_routes(client, engine):
    before = client.get("/api/materials").json()
    with Session(engine) as db, db.begin():
        seed(db)
    assert client.get("/api/materials").json() == before
    assert len(before) == 24
    for material in before:
        if material["procurement"] == "E":
            assert client.get(f"/api/routing/{material['matnr']}").json()
    tree = client.get("/api/bom/EB-1000?valid_on=2026-11-02").json()
    assert tree["revision"] == "A"
    battery = next(c for c in next(c for c in tree["children"] if c["matnr"] == "PU-400")["children"] if c["matnr"] == "BP-402")
    assert next(c for c in battery["children"] if c["matnr"] == "CL-4021")["qty"] == 30


def test_multilevel_baseline_and_planning_does_not_change_stock(client):
    demand(client)
    before = client.get("/api/materials").json()
    result = plan(client)
    assert client.get("/api/materials").json() == before
    planned = {p["matnr"]: p for p in proposals(client)}
    assert len([p for p in planned.values() if p["kind"] == "MAKE"]) == 6
    assert planned["CL-4021"]["qty"] == 6000
    assert planned["TY-203"]["qty"] == 400
    assert planned["PT-103"]["qty"] == 100
    assert planned["BP-402"]["qty"] == 200
    assert planned["EB-1000"]["start"] == "2026-12-01"
    assert planned["CL-4021"]["due"] == "2026-11-29"
    assert planned["CL-4021"]["start"] == "2026-11-26"
    assert not result["exceptions"]


def test_existing_assembly_stock_reduces_explosion(client, engine):
    with Session(engine) as db, db.begin():
        move(db, "EB-1000", 20, "OPENING", "TEST")
        move(db, "BP-402", 30, "OPENING", "TEST")
    demand(client)
    plan(client)
    planned = {p["matnr"]: p["qty"] for p in proposals(client)}
    assert planned["EB-1000"] == 180
    assert planned["BP-402"] == 150
    assert planned["CL-4021"] == 4500


@pytest.mark.parametrize("rule,lot_size,expected", [("LFL", 100, 110), ("FIXED", 100, 200), ("MIN", 200, 200)])
def test_safety_stock_and_lot_sizing(client, engine, rule, lot_size, expected):
    with Session(engine) as db, db.begin():
        material = db.get(Material, "TY-203")
        material.lot_rule, material.lot_qty, material.safety = rule, Decimal(lot_size), Decimal(10)
    demand(client, 100, "TY-203")
    plan(client)
    assert proposals(client)[0]["qty"] == expected


def test_multiple_dates_carry_lot_excess_and_safety_floor(client, engine):
    with Session(engine) as db, db.begin():
        material = db.get(Material, "TY-203")
        material.lot_rule, material.lot_qty, material.safety = "FIXED", Decimal(100), Decimal(10)
    demand(client, 30, "TY-203", "2026-12-01")
    demand(client, 40, "TY-203", "2026-12-02")
    result = plan(client)
    assert [p["qty"] for p in proposals(client)] == [100]
    assert [r["projected"] for r in result["rows"] if r["type"] != "Opening stock"] == [70, 30]


def test_shared_component_aggregates_after_all_parents(client, engine):
    with Session(engine) as db, db.begin():
        frame = db.scalar(select(Bom).where(Bom.matnr == "FR-100"))
        db.add(BomItem(bom_id=frame.id, component="CL-4021", qty=2))
    demand(client, 10)
    plan(client)
    assert sum(p["qty"] for p in proposals(client) if p["matnr"] == "CL-4021") == 320


def test_rerun_supersedes_proposals_without_duplicate_supply(client):
    demand(client)
    first = plan(client)
    initial = proposals(client)
    second = plan(client)
    current = proposals(client)
    assert len(current) == len(initial)
    assert {(p["matnr"], p["qty"]) for p in current} == {(p["matnr"], p["qty"]) for p in initial}
    assert first["id"] != second["id"]
    assert all(p["run_id"] == second["id"] for p in current)
    old_id = next(p["id"] for p in initial if p["kind"] == "MAKE")
    post(client, "/orders/convert", {"proposal_id": old_id}, 409)


def test_committed_supply_is_date_sensitive_and_not_counted_twice(client):
    demand(client, 100, "TY-203", "2026-12-02")
    plan(client)
    pr = proposals(client)[0]
    keyed(client, f"/purchase-requisitions/{pr['id']}/goods-receipt", qty=20)
    plan(client)
    assert not proposals(client)
    demand(client, 50, "TY-203", "2026-12-01")
    plan(client)
    assert [(p["due"], p["qty"]) for p in proposals(client)] == [("2026-12-01", 30), ("2026-12-02", 20)]


def test_converted_supply_and_reservations_not_double_netted(client):
    demand(client, 10)
    plan(client)
    p = next(p for p in proposals(client) if p["matnr"] == "EB-1000")
    order = post(client, "/orders/convert", {"proposal_id": p["id"]}, 201)
    keyed(client, f"/orders/{order['id']}/release")
    plan(client)
    current = {p["matnr"]: p["qty"] for p in proposals(client)}
    assert "EB-1000" not in current
    assert current["FR-100"] == 10
    assert current["CL-4021"] == 300


def test_invalid_inputs_and_missing_demand(client):
    post(client, "/requirements", {"matnr": "EB-1000", "qty": -1, "due": "2026-12-02"}, 422)
    post(client, "/requirements", {"matnr": "EB-1000", "qty": 0.5, "due": "2026-12-02"}, 422)
    post(client, "/requirements", {"matnr": "EB-1000", "qty": 1, "due": "bad-date"}, 422)
    post(client, "/requirements", {"matnr": "MISSING", "qty": 1, "due": "2026-12-02"}, 404)
    post(client, "/mrp/run", {"planning_date": "2026-11-02"}, 422)
    demand(client, 1.25, "PT-103")
    plan(client)
    assert proposals(client)[0]["qty"] == 1.25


def test_past_dates_reported(client):
    demand(client, 1, due="2026-11-03")
    result = plan(client)
    assert result["exceptions"]
    assert all("precedes planning date" in e["message"] for e in result["exceptions"])


def test_cycle_rejected_and_draft_creation_rolls_back(client):
    payload = {"matnr": "PU-400", "revision": "B", "valid_from": "2026-11-10", "reason": "Invalid recursive BOM",
               "components": [{"component": "EB-1000", "qty": 1}]}
    post(client, "/ecn", payload, 422)
    assert not client.get("/api/ecn").json()
    assert len(client.get("/api/bom-revisions").json()) == 6


def test_effectivity_boundary_draft_exclusion_and_old_order_snapshot(client):
    demand(client, 1, "PU-400", "2026-11-12")
    plan(client)
    p = next(p for p in proposals(client) if p["matnr"] == "PU-400")
    order = post(client, "/orders/convert", {"proposal_id": p["id"]}, 201)
    ecn = change(client)
    cid = ecn["id"]
    get_tree = lambda day: client.get(f"/api/bom/PU-400?valid_on={day}").json()
    assert get_tree("2026-11-10")["revision"] == "A"
    post(client, f"/ecn/{cid}/status", {"target": "Released"}, 409)
    post(client, f"/ecn/{cid}/status", {"target": "Approved"})
    post(client, f"/ecn/{cid}/status", {"target": "Released"})
    assert get_tree("2026-11-09")["revision"] == "A"
    assert get_tree("2026-11-10")["revision"] == "B"
    old = client.get(f"/api/orders/{order['id']}").json()
    assert "CT-403" in {c["matnr"] for c in old["components"]}
    assert "CT-404" not in {c["matnr"] for c in old["components"]}
    impact = client.get(f"/api/ecn/{cid}/impact").json()
    assert any(r["type"] == "Production order" and r["id"] == order["id"] for r in impact)
    demand(client, 1, "PU-400", "2026-11-12")
    plan(client)
    new_p = next(p for p in proposals(client) if p["matnr"] == "PU-400")
    new_order = post(client, "/orders/convert", {"proposal_id": new_p["id"]}, 201)
    assert "CT-404" in {c["matnr"] for c in new_order["components"]}


def test_duplicate_revision_start_and_nested_impact(client):
    demand(client, 1)
    plan(client)
    ecn = change(client)
    impact = client.get(f"/api/ecn/{ecn['id']}/impact").json()
    assert {r["matnr"] for r in impact} >= {"EB-1000", "PU-400"}
    post(client, "/ecn", {"matnr": "PU-400", "revision": "C", "valid_from": "2026-11-10", "reason": "Duplicate start date",
                          "components": [{"component": "CT-404", "qty": 1}]}, 409)


def test_posting_replay_conflict_and_receipt_limits(client):
    demand(client, 10, "TY-203")
    plan(client)
    pr = proposals(client)[0]
    path = f"/purchase-requisitions/{pr['id']}/goods-receipt"
    payload = {"key": str(uuid4()), "qty": 4}
    first = post(client, path, payload)
    assert post(client, path, payload) == first
    assert client.get("/api/materials/TY-203").json()["stock"] == 4
    post(client, path, {**payload, "qty": 5}, 409)
    post(client, path, {"key": str(uuid4()), "qty": 7}, 409)
    assert client.get("/api/materials/TY-203").json()["stock"] == 4


def test_concurrent_receipts_cannot_overreceive(client):
    demand(client, 10, "TY-203")
    plan(client)
    pr = proposals(client)[0]
    def receive(_):
        return client.post(f"/api/purchase-requisitions/{pr['id']}/goods-receipt", json={"key": str(uuid4()), "qty": 7}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(receive, range(2))) == [200, 409]
    assert client.get("/api/materials/TY-203").json()["stock"] == 7


def test_issue_failure_rolls_back_every_material_and_event(client, engine):
    demand(client, 1, "FR-100")
    plan(client)
    p = next(p for p in proposals(client) if p["matnr"] == "FR-100")
    order = post(client, "/orders/convert", {"proposal_id": p["id"]}, 201)
    with Session(engine) as db, db.begin():
        move(db, "TB-101", 1, "OPENING", "TEST")
    keyed(client, f"/orders/{order['id']}/release")
    before_events = client.get("/api/events").json()
    before_moves = client.get("/api/movements").json()
    post(client, f"/orders/{order['id']}/goods-issue", {"key": str(uuid4())}, 409)
    assert client.get("/api/materials/TB-101").json()["stock"] == 1
    assert client.get("/api/movements").json() == before_moves
    assert client.get("/api/events").json() == before_events


def test_full_200_bike_cycle_and_stock_reconciliation(client):
    demand(client)
    plan(client)
    ps = proposals(client)
    for p in ps:
        if p["kind"] == "BUY":
            keyed(client, f"/purchase-requisitions/{p['id']}/goods-receipt", qty=p["qty"])
    for code in ["BP-402", "FR-100", "WH-200", "DT-300", "PU-400", "EB-1000"]:
        p = next(p for p in ps if p["matnr"] == code)
        order = post(client, "/orders/convert", {"proposal_id": p["id"]}, 201)
        post(client, "/orders/convert", {"proposal_id": p["id"]}, 409)
        complete = finish(client, order)
        assert complete["status"] == "TECO"
        assert complete["actual_cost"] == complete["planned_cost"]
        post(client, f"/orders/{order['id']}/goods-receipt", {"key": str(uuid4()), "qty": 1}, 409)
    balances = defaultdict(Decimal)
    for movement in client.get("/api/movements").json():
        balances[movement["matnr"]] += Decimal(str(movement["qty"]))
    for material in client.get("/api/materials").json():
        assert Decimal(str(material["stock"])) == balances[material["matnr"]]
    assert client.get("/api/materials/EB-1000").json()["stock"] == 200
    assert {e["module"] for e in client.get("/api/events").json()} >= {"PP", "MM", "SD", "CO", "QM", "MM / FI"}
    plan(client)
    assert not proposals(client)


def test_partial_confirmation_receipts_and_illegal_transitions(client):
    demand(client, 2, "WH-200")
    plan(client)
    ps = proposals(client)
    for p in ps:
        if p["kind"] == "BUY":
            keyed(client, f"/purchase-requisitions/{p['id']}/goods-receipt", qty=p["qty"])
    order = post(client, "/orders/convert", {"proposal_id": next(p["id"] for p in ps if p["matnr"] == "WH-200")}, 201)
    oid = order["id"]
    post(client, f"/orders/{oid}/complete", {"key": str(uuid4())}, 409)
    keyed(client, f"/orders/{oid}/release")
    assert client.get("/api/materials/RM-201").json()["stock"] == 4
    post(client, f"/orders/{oid}/confirm", {"key": str(uuid4()), "op": "0010", "yield_qty": 2, "minutes": 34, "final": True}, 409)
    keyed(client, f"/orders/{oid}/goods-issue")
    partial = keyed(client, f"/orders/{oid}/confirm", op="0010", yield_qty=1, scrap=0, minutes=22, final=False)
    assert partial["status"] == "PCNF"
    post(client, f"/orders/{oid}/goods-receipt", {"key": str(uuid4()), "qty": 2}, 409)
    keyed(client, f"/orders/{oid}/goods-receipt", qty=1)
    keyed(client, f"/orders/{oid}/confirm", op="0010", yield_qty=1, scrap=0, minutes=12, final=True)
    delivered = keyed(client, f"/orders/{oid}/goods-receipt", qty=1)
    assert delivered["status"] == "DLV"
    assert keyed(client, f"/orders/{oid}/complete")["status"] == "TECO"


def test_routing_snapshot_and_operation_sequence(client):
    demand(client, 1, "FR-100")
    plan(client)
    ps = proposals(client)
    for p in ps:
        if p["kind"] == "BUY":
            keyed(client, f"/purchase-requisitions/{p['id']}/goods-receipt", qty=p["qty"])
    order = post(client, "/orders/convert", {"proposal_id": next(p["id"] for p in ps if p["matnr"] == "FR-100")}, 201)
    new_routes = {"matnr": "FR-100", "operations": [{"op": "0010", "center": "WC-TEST", "description": "Changed route", "setup": 1, "run": 1}]}
    assert client.put("/api/routing/FR-100", json=new_routes).status_code == 200
    assert len(client.get(f"/api/orders/{order['id']}").json()["operations"]) == 2
    keyed(client, f"/orders/{order['id']}/release")
    keyed(client, f"/orders/{order['id']}/goods-issue")
    post(client, f"/orders/{order['id']}/confirm", {"key": str(uuid4()), "op": "0020", "yield_qty": 1, "minutes": 1, "final": True}, 409)


def test_reset_reconciles_demo_stock_and_can_be_disabled(client, monkeypatch):
    demand(client)
    plan(client)
    post(client, "/demo/reset", {"fixture": "demo", "confirmation": "RESET DEMO DATA"})
    assert not client.get("/api/orders").json()
    assert not client.get("/api/requirements").json()
    assert not client.get("/api/mrp/runs").json()
    assert client.get("/api/materials/CL-4021").json()["stock"] == 100
    monkeypatch.setenv("ENABLE_DEMO_RESET", "0")
    post(client, "/demo/reset", {"fixture": "zero", "confirmation": "RESET DEMO DATA"}, 403)


def ready_order(client, matnr, qty):
    demand(client, qty, matnr)
    plan(client)
    ps = proposals(client)
    for proposal in ps:
        if proposal["kind"] == "BUY":
            keyed(client, f"/purchase-requisitions/{proposal['id']}/goods-receipt", qty=proposal["qty"])
    order = post(client, "/orders/convert", {"proposal_id": next(p["id"] for p in ps if p["matnr"] == matnr)}, 201)
    keyed(client, f"/orders/{order['id']}/release")
    keyed(client, f"/orders/{order['id']}/goods-issue")
    return order


def test_final_marker_after_all_yield_was_partially_confirmed(client):
    order = ready_order(client, "WH-200", 2)
    path = f"/orders/{order['id']}/confirm"
    partial = keyed(client, path, op="0010", yield_qty=2, scrap=0, minutes=34, final=False)
    assert partial["status"] == "PCNF"
    final = keyed(client, path, op="0010", yield_qty=0, scrap=0, minutes=0, final=True)
    assert final["status"] == "CNF"
    assert final["operations"][0]["yield"] == "2"
    assert final["actual_cost"] == partial["actual_cost"]
    assert keyed(client, f"/orders/{order['id']}/goods-receipt", qty=2)["status"] == "DLV"


def test_fractional_yield_and_scrap_cannot_cancel_to_whole_ea(client):
    order = ready_order(client, "WH-200", 2)
    path = f"/orders/{order['id']}/confirm"
    before = client.get(f"/api/orders/{order['id']}").json()
    post(client, path, {"key": str(uuid4()), "op": "0010", "yield_qty": 1.5, "scrap": 0.5, "minutes": 34, "final": True}, 422)
    assert client.get(f"/api/orders/{order['id']}").json() == before


def test_zero_input_can_close_operation_after_all_upstream_units_scrapped(client):
    order = ready_order(client, "FR-100", 1)
    path = f"/orders/{order['id']}/confirm"
    post(client, path, {"key": str(uuid4()), "op": "0010", "yield_qty": 0, "scrap": 0, "minutes": 0, "final": False}, 409)
    keyed(client, path, op="0010", yield_qty=0, scrap=1, minutes=25, final=True)
    result = keyed(client, path, op="0020", yield_qty=0, scrap=0, minutes=0, final=True)
    assert result["status"] == "CNF"
    assert result["received"] == 0
    post(client, f"/orders/{order['id']}/goods-receipt", {"key": str(uuid4()), "qty": 1}, 409)
