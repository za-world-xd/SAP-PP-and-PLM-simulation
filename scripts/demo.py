"""Prepare lower-level supply through the same API used by the web interface."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--reset", action="store_true", help="Explicitly replace all simulator data with the demo fixture")
    parser.add_argument("--finish", action="store_true", help="Also execute final bike assembly instead of leaving it for the browser")
    args = parser.parse_args()
    with httpx.Client(base_url=f"{args.url}/api", timeout=30) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, payload):
            response = client.post(path, json=payload)
            if response.is_error:
                raise RuntimeError(f"{path}: {response.text}")
            return response.json()

        def action(path, **payload):
            return post(path, {"key": str(uuid4()), **payload})

        if args.reset:
            post("/demo/reset", {"fixture": "demo", "confirmation": "RESET DEMO DATA"})
        if get("/orders"):
            parser.error("Orders already exist. Use the browser to continue, or --reset to explicitly replace demo data.")
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        if not get("/requirements"):
            post("/requirements", {"matnr": "EB-1000", "qty": 200, "due": (today + timedelta(days=30)).isoformat()})
        run = post("/mrp/run", {"planning_date": today.isoformat()})
        proposals = [p for p in get("/mrp/proposals") if p["status"] == "Open"]
        for proposal in proposals:
            if proposal["kind"] == "BUY":
                action(f"/purchase-requisitions/{proposal['id']}/goods-receipt", qty=proposal["qty"])

        final_order = None
        for code in ["BP-402", "FR-100", "WH-200", "DT-300", "PU-400", "EB-1000"]:
            for proposal in (p for p in proposals if p["matnr"] == code and p["kind"] == "MAKE"):
                order = post("/orders/convert", {"proposal_id": proposal["id"]})
                if code == "EB-1000" and not args.finish:
                    final_order = order
                    continue
                action(f"/orders/{order['id']}/release")
                action(f"/orders/{order['id']}/goods-issue")
                for operation in order["operations"]:
                    minutes = Decimal(str(operation["setup"])) + Decimal(str(operation["run"])) * Decimal(str(order["qty"]))
                    action(f"/orders/{order['id']}/confirm", op=operation["op"], yield_qty=order["qty"], scrap=0, minutes=str(minutes), final=True)
                action(f"/orders/{order['id']}/goods-receipt", qty=order["qty"])
                final_order = action(f"/orders/{order['id']}/complete")
                print(f"Completed {code}: {order['qty']:g} units")
        result = {"mrp_run": run["id"], "final_order": final_order, "dashboard": get("/dashboard")}
        path = Path(__file__).resolve().parents[1] / "artifacts" / "demo-result.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Ready at {args.url}. Final order ORD-{final_order['id']}: {final_order['status']}")
        print("Refresh the browser, open Production, then select the EB-1000 order.")


if __name__ == "__main__":
    main()

