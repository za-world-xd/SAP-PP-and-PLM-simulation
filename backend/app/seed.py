from decimal import Decimal

from sqlalchemy import select

from .models import Bom, BomItem, Material, Routing, WorkCenter


BOMS = {
    "EB-1000": [("FR-100", 1), ("WH-200", 1), ("DT-300", 1), ("PU-400", 1), ("BR-500", 1), ("DS-600", 1)],
    "FR-100": [("TB-101", 1), ("FK-102", 1), ("PT-103", "0.5")],
    "WH-200": [("RM-201", 2), ("SP-202", 2), ("TY-203", 2), ("HB-204", 2)],
    "DT-300": [("CR-301", 1), ("CH-302", 1), ("CS-303", 1)],
    "PU-400": [("MT-401", 1), ("BP-402", 1), ("CT-403", 1)],
    "BP-402": [("CL-4021", 30), ("BM-4022", 1), ("CS-4023", 1)],
}

NAMES = {
    "EB-1000": "City E-Bike 250W", "FR-100": "Frame Assembly", "WH-200": "Wheel Set",
    "DT-300": "Drivetrain", "PU-400": "Power Unit", "BP-402": "Battery pack 36V",
    "TB-101": "Aluminium tube set", "FK-102": "Front fork", "PT-103": "Paint, 2-coat",
    "RM-201": "Rim 700c", "SP-202": "Spoke set", "TY-203": "Tyre", "HB-204": "Hub",
    "CR-301": "Crankset", "CH-302": "Chain", "CS-303": "Cassette", "MT-401": "Hub motor 250W",
    "CT-403": "Controller", "CL-4021": "Li-ion cell 18650", "BM-4022": "BMS board",
    "CS-4023": "Pack casing", "BR-500": "Brake Set", "DS-600": "Display + wiring harness",
    "CT-404": "Controller, revision B",
}

CENTERS = [
    ("WC-WELD", "Frame welding", 40), ("WC-PAINT", "Painting and curing", 60),
    ("WC-WHEEL", "Wheel building", 50), ("WC-BATT", "Battery assembly", 30),
    ("WC-ASSY", "Final assembly", 25), ("WC-TEST", "End-of-line test", 40),
]

ROUTES = {
    "EB-1000": [("WC-ASSY", "Mount drivetrain and power unit", 15, 12), ("WC-ASSY", "Fit wheels and brakes", 10, 8), ("WC-ASSY", "Fit display and wiring", 5, 6), ("WC-TEST", "Functional and safety test", 10, 10)],
    "FR-100": [("WC-WELD", "Weld frame", 15, 10), ("WC-PAINT", "Paint and cure frame", 10, 8)],
    "WH-200": [("WC-WHEEL", "Build wheel set", 10, 12)],
    "DT-300": [("WC-ASSY", "Assemble drivetrain", 5, 6)],
    "BP-402": [("WC-BATT", "Assemble battery pack", 15, 15)],
    "PU-400": [("WC-ASSY", "Integrate power unit", 5, 8)],
}


def seed(db, fixture="demo"):
    if db.scalar(select(Material.matnr).limit(1)):
        return
    for code, name in NAMES.items():
        make = code in BOMS
        stock = 0 if fixture == "zero" or make else (100 if code == "CL-4021" else 10)
        db.add(Material(matnr=code, name=name, kind="FERT" if code == "EB-1000" else "HALB" if make else "ROH",
                        procurement="E" if make else "F", unit="L" if code == "PT-103" else "EA",
                        stock=stock, safety=0, lead_days=1 if make else 3, lot_rule="LFL", lot_qty=1,
                        cost=800 if code == "EB-1000" else 100 if make else 10))
    for code, name, capacity in CENTERS:
        db.add(WorkCenter(arbpl=code, name=name, units_per_shift=capacity, rate=2, shift_minutes=480))
    db.flush()
    for parent, children in BOMS.items():
        bom = Bom(matnr=parent, revision="A", valid_from="2020-01-01", status="Released")
        db.add(bom)
        db.flush()
        for child, qty in children:
            db.add(BomItem(bom_id=bom.id, component=child, qty=Decimal(str(qty))))
    for material, operations in ROUTES.items():
        for i, (center, description, setup, run) in enumerate(operations, 1):
            db.add(Routing(matnr=material, op=f"{i * 10:04}", center=center, description=description, setup=setup, run=run))
    db.flush()
    # Opening stock uses the same ledger as later movements for reconciliation.
    from .services.inventory import move
    for material in db.scalars(select(Material)).all():
        opening = material.stock
        material.stock = 0
        if opening:
            move(db, material.matnr, opening, "OPENING", "SEED")

