"""Synthetic UAE infrastructure dataset for the AI features (`make dev-seed-ai-demo`). Nothing here is real
tender, vendor or price data. Everything created in the database is tagged (project codes AI-DEMO*, vendor
names starting "AIDEMO ", cost item codes starting "AIDEMO-") so `make dev-clean-demo-data` removes it.

* cost library: ~150 items across earthworks, asphalt, kerbs, drainage and pipes (uPVC, DI, GRP by diameter),
  manholes, road marking, street lighting and landscaping, each with a current rate and an older one;
* vendors: 20, with trades, regions, prequalification (some expiring or lapsed) and certificates;
* win/loss history: 15 past tenders with margins, outcomes and priced lines;
* the tender pack (`build_pack`): DXF and vector-PDF drawings, an Excel BOQ, a PDF BOQ (with a scanned page),
  a specification, an addendum and a contract, arranged in folders, with deliberate matches, variances, a
  missing-in-BOQ item and missing-in-drawings items (see EXPECTED_CLASSES).
"""

from __future__ import annotations

import io
import random
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

DEMO_PROJECT_CODE = "AI-DEMO"
HISTORY_PROJECT_PREFIX = "AI-DEMO-H"
E2E_PROJECT_PREFIX = "AI-DEMO-E2E"  # projects created by the real-backend walkthrough, one per run
VENDOR_PREFIX = "AIDEMO "
COST_CODE_PREFIX = "AIDEMO-"
PACK_ROOT = "Al Reem Package 3"

TRADE_EARTH, TRADE_ASPHALT, TRADE_CONCRETE, TRADE_MEP, TRADE_UTIL = "EARTH", "ASPHALT", "CONCRETE", "MEP", "UTIL"


# ================================================================== cost library

@dataclass(frozen=True, slots=True)
class LibItem:
    code: str
    description: str
    uom: str
    trade: str
    rate: float
    prior_rate: float | None = None  # an older rate (kept for history)


def _lib() -> list[LibItem]:
    items: list[LibItem] = []

    def add(code, desc, uom, trade, rate, prior=None):
        items.append(LibItem(f"{COST_CODE_PREFIX}{code}", desc, uom, trade, float(rate), prior))

    # earthworks (12)
    for code, desc, uom, rate in [
        ("EW-001", "Excavate in all types of soil and dispose off site", "m3", 18.5), ("EW-002", "Excavate in rock and dispose off site", "m3", 68.0),
        ("EW-003", "Backfill with approved selected material compacted in layers", "m3", 24.0), ("EW-004", "Supply and place approved granular sub-base 200mm compacted", "m3", 62.0),
        ("EW-005", "Trim and compact formation level to receive sub-base", "m2", 3.6), ("EW-006", "Supply and spread topsoil 200mm", "m2", 9.5),
        ("EW-007", "Geotextile separation layer", "m2", 6.2), ("EW-008", "Hardcore fill compacted", "m3", 55.0),
        ("EW-009", "Sand bedding and surround to pipes", "m3", 48.0), ("EW-010", "Dewatering of excavations", "m", 14.0),
        ("EW-011", "Import approved fill from borrow pit", "m3", 31.0), ("EW-012", "Proof rolling of formation", "m2", 1.8),
    ]:
        add(code, desc, uom, TRADE_EARTH, rate, rate * 0.92)
    # asphalt (10)
    for code, desc, uom, rate in [
        ("AS-001", "Asphalt wearing course 50mm thick", "m2", 46.0), ("AS-002", "Asphalt binder course 60mm thick", "m2", 52.0),
        ("AS-003", "Asphalt base course 100mm thick", "m2", 78.0), ("AS-004", "Tack coat", "m2", 2.4), ("AS-005", "Prime coat", "m2", 3.1),
        ("AS-006", "Cold planing of existing asphalt 50mm", "m2", 9.5), ("AS-007", "Crack sealing", "m", 7.0),
        ("AS-008", "Asphalt patching", "m2", 88.0), ("AS-009", "Bituminous surface dressing", "m2", 12.5), ("AS-010", "Interlocking paver 80mm", "m2", 95.0),
    ]:
        add(code, desc, uom, TRADE_ASPHALT, rate, rate * 0.9)
    # kerbs (8)
    for code, desc, uom, rate in [
        ("KB-001", "Precast concrete kerb Type A 300x150", "m", 42.0), ("KB-002", "Precast concrete kerb Type B 250x125", "m", 38.0),
        ("KB-003", "Precast concrete kerb Type C dropped", "m", 46.0), ("KB-004", "Precast concrete edge restraint", "m", 26.0),
        ("KB-005", "Precast concrete channel 300mm", "m", 44.0), ("KB-006", "Concrete kerb cast in situ", "m", 58.0),
        ("KB-007", "Granite kerb 300x150", "m", 120.0), ("KB-008", "Kerb haunching concrete", "m", 18.0),
    ]:
        add(code, desc, uom, TRADE_CONCRETE, rate, rate * 0.93)
    # drainage pipes: uPVC SN8 supply and lay by diameter (8), supply only (4), DI (5), GRP (5), HDPE (4)
    for dia, rate in [(150, 71.0), (200, 92.0), (250, 118.0), (300, 96.0), (375, 152.0), (450, 198.0), (525, 246.0), (600, 305.0)]:
        add(f"PP-UPVC-{dia}", f"uPVC SN8 sewer pipe {dia}mm diameter supply and lay in trench", "m", TRADE_UTIL, rate, rate * 0.9)
    for dia, rate in [(150, 38.0), (200, 52.0), (300, 70.0), (450, 128.0)]:
        add(f"PP-UPVC-S-{dia}", f"uPVC SN8 pipe {dia}mm diameter supply only", "m", TRADE_UTIL, rate, rate * 0.9)
    for dia, rate in [(100, 96.0), (150, 138.0), (200, 188.0), (300, 296.0), (400, 410.0)]:
        add(f"PP-DI-{dia}", f"Ductile iron pipe {dia}mm diameter supply and lay", "m", TRADE_UTIL, rate, rate * 0.94)
    for dia, rate in [(450, 340.0), (600, 468.0), (800, 690.0), (1000, 940.0), (1200, 1290.0)]:
        add(f"PP-GRP-{dia}", f"GRP pipe {dia}mm diameter supply and lay", "m", TRADE_UTIL, rate, rate * 0.92)
    for dia, rate in [(110, 44.0), (160, 68.0), (225, 112.0), (315, 176.0)]:
        add(f"PP-HDPE-{dia}", f"HDPE pipe {dia}mm diameter supply and lay", "m", TRADE_UTIL, rate, rate * 0.9)
    # manholes / gullies / catchpits / covers (16)
    for dia, depth, rate in [(1200, "up to 2m", 3900.0), (1200, "2 to 3m", 4700.0), (1200, "3 to 4m", 5600.0), (1500, "up to 2m", 5200.0),
                             (1500, "2 to 3m", 6200.0), (1500, "3 to 4m", 7300.0), (1800, "up to 3m", 8400.0), (1800, "3 to 5m", 10200.0)]:
        add(f"MH-{dia}-{depth[:2].strip().replace(' ', '')}", f"Precast concrete manhole {dia}mm internal diameter, depth {depth}, complete", "nr", TRADE_CONCRETE, rate, rate * 0.94)
    for code, desc, rate in [("GU-001", "Road gully with precast chamber and grating", 1450.0), ("GU-002", "Road gully double outlet", 2100.0),
                             ("CP-001", "Catchpit 900x900 precast", 2600.0), ("CP-002", "Catchpit 1200x1200 precast", 3400.0)]:
        add(code, desc, "nr", TRADE_CONCRETE, rate, rate * 0.95)
    for code, desc, rate in [("CV-001", "Ductile iron manhole cover and frame class D400", 780.0), ("CV-002", "Ductile iron manhole cover class B125", 520.0),
                             ("CV-003", "Gully grating cast iron", 340.0), ("CV-004", "Step irons galvanised set", 190.0)]:
        add(code, desc, "nr", TRADE_CONCRETE, rate, rate * 0.95)
    # road marking (8)
    for code, desc, uom, rate in [
        ("RM-001", "Thermoplastic road marking 100mm centre line", "m", 6.8), ("RM-002", "Thermoplastic road marking 150mm edge line", "m", 8.2),
        ("RM-003", "Thermoplastic road marking arrows", "nr", 165.0), ("RM-004", "Thermoplastic road marking symbols and legends", "nr", 240.0),
        ("RM-005", "Cat eyes reflective road studs", "nr", 58.0), ("RM-006", "Zebra crossing marking", "m2", 92.0),
        ("RM-007", "Traffic sign post and sign 600mm", "nr", 640.0), ("RM-008", "Guardrail galvanised", "m", 210.0),
    ]:
        add(code, desc, uom, TRADE_ASPHALT, rate, rate * 0.92)
    # street lighting (14)
    for h, rate in [(6, 3800.0), (8, 4600.0), (10, 5900.0), (12, 7400.0)]:
        add(f"SL-COL-{h}", f"Street lighting column {h}m complete with bracket and foundation", "nr", TRADE_MEP, rate, rate * 0.93)
    for w, rate in [(60, 1450.0), (90, 1850.0), (150, 2650.0)]:
        add(f"SL-LUM-{w}", f"LED luminaire {w}W supply and install", "nr", TRADE_MEP, rate, rate * 0.9)
    for code, desc, uom, rate in [
        ("SL-CAB-16", "Armoured cable 4c 16mm2 supply and lay", "m", 46.0), ("SL-CAB-35", "Armoured cable 4c 35mm2 supply and lay", "m", 78.0),
        ("SL-DUCT-110", "PVC duct 110mm in trench", "m", 34.0), ("SL-FP-001", "Feeder pillar complete", "nr", 9800.0),
        ("SL-JB-001", "Cable joint box", "nr", 620.0), ("SL-EARTH", "Earthing rod and connection", "nr", 380.0), ("SL-TEST", "Testing and commissioning of lighting circuit", "nr", 1200.0),
    ]:
        add(code, desc, uom, TRADE_MEP, rate, rate * 0.92)
    # landscaping (14) -- one deliberately old (stale) rate
    for code, desc, uom, rate in [
        ("LS-TURF", "Turfing with irrigation ready subgrade", "m2", 24.0), ("LS-TOPSOIL", "Topsoil 200mm supply and spread", "m2", 9.5),
        ("LS-TREE-GHAF", "Ghaf tree 2.5m height supply and plant", "nr", 1350.0), ("LS-TREE-PALM", "Date palm 4m clear trunk supply and plant", "nr", 4800.0),
        ("LS-TREE-NEEM", "Neem tree 3m supply and plant", "nr", 1180.0), ("LS-SHRUB", "Shrub 3 litre supply and plant", "nr", 38.0),
        ("LS-GRASS", "Ornamental grass 3 litre", "nr", 32.0), ("LS-IRR-PIPE", "Irrigation pipe 50mm HDPE", "m", 28.0),
        ("LS-IRR-DRIP", "Drip irrigation line", "m", 9.0), ("LS-MULCH", "Gravel mulch 50mm", "m2", 22.0),
        ("LS-EDGE", "Aluminium landscape edging", "m", 52.0), ("LS-BENCH", "Park bench precast", "nr", 3400.0),
        ("LS-BIN", "Litter bin stainless", "nr", 1250.0), ("LS-SHADE", "Shade sail structure", "nr", 18500.0),
    ]:
        add(code, desc, uom, TRADE_EARTH, rate, rate * 0.9)
    # water mains and valves (14)
    for dia, rate in [(63, 32.0), (110, 58.0), (160, 96.0), (225, 158.0), (315, 246.0)]:
        add(f"WM-PE-{dia}", f"PE100 water main {dia}mm diameter supply and lay", "m", TRADE_UTIL, rate, rate * 0.92)
    for dia, rate in [(80, 1350.0), (150, 2400.0), (200, 3600.0), (300, 6200.0)]:
        add(f"WM-VLV-{dia}", f"Gate valve {dia}mm with chamber", "nr", TRADE_UTIL, rate, rate * 0.94)
    for code, desc, rate in [("WM-HYD-1", "Fire hydrant complete with chamber", 5200.0), ("WM-AIR-1", "Air valve assembly", 2800.0),
                             ("WM-WSH-1", "Washout assembly", 2100.0), ("WM-THR-1", "Concrete thrust block", 640.0), ("WM-CON-1", "Connection to existing water main", 7400.0)]:
        add(code, desc, "nr", TRADE_UTIL, rate, rate * 0.94)
    # culverts and structures (8)
    for code, desc, uom, rate in [
        ("CU-BOX-1510", "Precast box culvert 1500x1000 supply and install", "m", 2350.0), ("CU-BOX-2015", "Precast box culvert 2000x1500 supply and install", "m", 3600.0),
        ("CU-HW-001", "Headwall reinforced concrete", "nr", 14800.0), ("CU-WW-001", "Wing wall reinforced concrete", "nr", 9600.0),
        ("CN-C35", "Structural concrete C35 supply and place", "m3", 720.0), ("CN-REBAR", "Reinforcement steel supply, cut, bend and fix", "t", 4100.0),
        ("CN-FORM", "Formwork to structural concrete", "m2", 95.0), ("CN-BLIND", "Blinding concrete C15 100mm", "m2", 42.0),
    ]:
        add(code, desc, uom, TRADE_CONCRETE, rate, rate * 0.93)
    # ducts, telecom and utilities crossings (8)
    for code, desc, uom, rate in [
        ("DU-110-2", "Two-way PVC duct bank 110mm in trench", "m", 88.0), ("DU-110-4", "Four-way PVC duct bank 110mm in trench", "m", 142.0),
        ("DU-JB-1", "Pull box 600x600", "nr", 1450.0), ("DU-MK-1", "Warning tape and marker posts", "m", 4.5),
        ("UT-XING-1", "Utility crossing protection slab", "nr", 3800.0), ("UT-LOC-1", "Utility location survey and trial holes", "nr", 950.0),
        ("UT-DIV-1", "Temporary diversion of existing service", "nr", 12500.0), ("UT-ENC-1", "Concrete encasement to existing service", "m", 380.0),
    ]:
        add(code, desc, uom, TRADE_UTIL, rate, rate * 0.92)
    # street furniture, barriers, signs (6)
    for code, desc, uom, rate in [
        ("SF-FENCE", "Chain link fence 2m high", "m", 145.0), ("SF-BARR", "Concrete barrier New Jersey", "m", 310.0),
        ("SF-BOLL", "Bollard removable", "nr", 480.0), ("SF-SIGN", "Regulatory road sign 900mm", "nr", 720.0),
        ("SF-PED", "Pedestrian guardrail", "m", 260.0), ("SF-SPEED", "Speed hump precast", "m", 520.0),
    ]:
        add(code, desc, uom, TRADE_ASPHALT, rate, rate * 0.93)
    # extra asphalt / paving / kerb finishes (6)
    for code, desc, uom, rate in [
        ("PV-CONC", "Concrete paving 150mm", "m2", 88.0), ("PV-TACT", "Tactile paving", "m2", 145.0), ("PV-CURB-RAMP", "Kerb ramp precast", "nr", 890.0),
        ("AS-MILL", "Milling and overlay 40mm", "m2", 38.0), ("AS-JOINT", "Asphalt joint sealing", "m", 9.0), ("AS-GEOGRID", "Geogrid reinforcement", "m2", 18.0),
    ]:
        add(code, desc, uom, TRADE_ASPHALT, rate, rate * 0.92)
    return items


COST_LIBRARY: list[LibItem] = _lib()
# a rate whose latest price is old: the assistant must flag it as stale against a 2026 tender
STALE_LIBRARY_CODES = {f"{COST_CODE_PREFIX}MH-1200-up", f"{COST_CODE_PREFIX}LS-TREE-GHAF"}


# ================================================================== vendors

@dataclass(frozen=True, slots=True)
class VendorSpec:
    name: str
    trades: tuple[str, ...]
    emirate: str
    regions: tuple[str, ...]
    prequal: str  # approved | expiring | lapsed | pending
    cert_days: int  # trade-licence expiry offset in days from today


VENDORS: list[VendorSpec] = [
    VendorSpec(f"{VENDOR_PREFIX}Gulf Earthmoving LLC", (TRADE_EARTH,), "Abu Dhabi", ("Abu Dhabi", "Dubai"), "approved", 300),
    VendorSpec(f"{VENDOR_PREFIX}Emirates Roadworks Co", (TRADE_ASPHALT, TRADE_EARTH), "Dubai", ("Dubai", "Sharjah", "Abu Dhabi"), "approved", 220),
    VendorSpec(f"{VENDOR_PREFIX}Al Noor Asphalt Industries", (TRADE_ASPHALT,), "Sharjah", ("Sharjah", "Dubai"), "approved", 160),
    VendorSpec(f"{VENDOR_PREFIX}Precast Arabia FZE", (TRADE_CONCRETE,), "Ajman", ("Ajman", "Dubai", "Sharjah", "Abu Dhabi"), "approved", 400),
    VendorSpec(f"{VENDOR_PREFIX}Dubai Concrete Products", (TRADE_CONCRETE,), "Dubai", ("Dubai", "Sharjah"), "expiring", 12),
    VendorSpec(f"{VENDOR_PREFIX}National Pipes Trading", (TRADE_UTIL,), "Dubai", ("Dubai", "Abu Dhabi", "Sharjah"), "approved", 250),
    VendorSpec(f"{VENDOR_PREFIX}Gulf GRP Systems", (TRADE_UTIL,), "Abu Dhabi", ("Abu Dhabi",), "approved", 180),
    VendorSpec(f"{VENDOR_PREFIX}Sanad Drainage Contracting", (TRADE_UTIL, TRADE_EARTH), "Dubai", ("Dubai", "Sharjah"), "approved", 340),
    VendorSpec(f"{VENDOR_PREFIX}Falcon Utilities LLC", (TRADE_UTIL,), "Abu Dhabi", ("Abu Dhabi",), "lapsed", -45),
    VendorSpec(f"{VENDOR_PREFIX}Bright Lighting Solutions", (TRADE_MEP,), "Dubai", ("Dubai", "Abu Dhabi", "Sharjah"), "approved", 280),
    VendorSpec(f"{VENDOR_PREFIX}Al Waha Electrical", (TRADE_MEP,), "Sharjah", ("Sharjah", "Ajman"), "expiring", 20),
    VendorSpec(f"{VENDOR_PREFIX}Desert Green Landscaping", (TRADE_EARTH,), "Dubai", ("Dubai", "Abu Dhabi"), "approved", 190),
    VendorSpec(f"{VENDOR_PREFIX}Oasis Nurseries", (TRADE_EARTH,), "Al Ain", ("Abu Dhabi", "Al Ain"), "approved", 260),
    VendorSpec(f"{VENDOR_PREFIX}Marking Masters", (TRADE_ASPHALT,), "Dubai", ("Dubai", "Sharjah", "Abu Dhabi"), "approved", 150),
    VendorSpec(f"{VENDOR_PREFIX}Highway Safety Products", (TRADE_ASPHALT,), "Ras Al Khaimah", ("Dubai", "Ras Al Khaimah"), "pending", 90),
    VendorSpec(f"{VENDOR_PREFIX}Emirates Cable & Duct", (TRADE_MEP, TRADE_UTIL), "Dubai", ("Dubai", "Sharjah"), "approved", 210),
    VendorSpec(f"{VENDOR_PREFIX}Tawam Aggregates", (TRADE_EARTH,), "Al Ain", ("Abu Dhabi", "Al Ain"), "approved", 330),
    VendorSpec(f"{VENDOR_PREFIX}Meydan Infrastructure Group", (TRADE_EARTH, TRADE_UTIL, TRADE_CONCRETE), "Dubai", ("Dubai", "Abu Dhabi", "Sharjah"), "approved", 365),
    VendorSpec(f"{VENDOR_PREFIX}Khalifa Precast & Pavers", (TRADE_CONCRETE, TRADE_ASPHALT), "Abu Dhabi", ("Abu Dhabi",), "approved", 100),
    VendorSpec(f"{VENDOR_PREFIX}Sahara Pipeline Services", (TRADE_UTIL,), "Fujairah", ("Fujairah", "Sharjah"), "expiring", 25),
]


# ================================================================== the demo project's BOQ

@dataclass(frozen=True, slots=True)
class BoqLine:
    item_no: str
    description: str
    uom: str | None
    qty: float | None
    trade: str | None = None
    expected: str | None = None  # expected verification class (None = heading)
    note: str = ""


BOQ: list[BoqLine] = [
    BoqLine("1", "EARTHWORKS", None, None),
    BoqLine("1.1", "Excavate in all types of soil for roadway and dispose off site", "m3", 12500.0, TRADE_EARTH, "match", "annotated: EXCAVATION 12,480 m3"),
    BoqLine("1.2", "Trim and compact formation level to receive sub-base", "m2", 7300.0, TRADE_EARTH, "match", "measured: road corridor area 7,280 m2"),
    BoqLine("1.3", "Supply and place approved granular sub-base 200mm compacted", "m3", 1460.0, TRADE_EARTH, "missing_in_drawings", "no drawing shows the pavement build-up"),
    BoqLine("2", "DRAINAGE", None, None),
    BoqLine("2.1", "Supply, lay and joint 300mm diameter uPVC SN8 sewer pipe including bedding and testing", "m", 245.0, TRADE_UTIL, "match", "measured: 3 runs 246 m"),
    BoqLine("2.2", "Supply, lay and joint 150mm diameter uPVC SN8 sewer pipe including bedding and testing", "m", 100.0, TRADE_UTIL, "variance", "measured 150 m (+50%)"),
    BoqLine("2.3", "Precast concrete manhole 1200mm internal diameter complete with cover and frame", "nr", 12.0, TRADE_CONCRETE, "match", "annotated: 12 nos"),
    BoqLine("2.4", "Connection to existing manhole including core drilling", "nr", 2.0, TRADE_UTIL, "missing_in_drawings", "not drawn"),
    BoqLine("3", "ROADWORKS", None, None),
    BoqLine("3.1", "Supply and lay asphalt wearing course 50mm thick", "m2", 7300.0, TRADE_ASPHALT, "match", "measured corridor area or annotation 7,300 m2"),
    BoqLine("3.2", "Precast concrete kerb Type A 300x150 supply and lay", "m", 1040.0, TRADE_CONCRETE, "match", "annotated: KERB L=1,040.0m"),
    BoqLine("3.3", "Thermoplastic road marking 100mm centre line", "m", 520.0, TRADE_ASPHALT, "match", "measured: alignment 520 m"),
    BoqLine("3.4", "Thermoplastic road marking arrows and symbols", "nr", 24.0, TRADE_ASPHALT, "missing_in_drawings", "no marking plan"),
    BoqLine("4", "STREET LIGHTING", None, None),
    BoqLine("4.1", "Street lighting column 8m complete with LED luminaire and foundation", "nr", 32.0, TRADE_MEP, "missing_in_drawings", "no lighting drawing in the package"),
    BoqLine("4.2", "Armoured cable 4c 16mm2 supply and lay in duct", "m", 2800.0, TRADE_MEP, "missing_in_drawings", "no lighting drawing in the package"),
    BoqLine("5", "LANDSCAPING", None, None),
    BoqLine("5.1", "Supply and spread topsoil 200mm thick", "m2", 4200.0, TRADE_EARTH, "match", "annotated: TOPSOIL 4,200 m2"),
    BoqLine("5.2", "Supply and plant Ghaf tree 2.5m height", "nr", 40.0, TRADE_EARTH, "variance", "annotated 46 nos (+15%)"),
    BoqLine("5.3", "Turfing with irrigation ready subgrade", "m2", 3100.0, TRADE_EARTH, "match", "annotated: TURF 3,100 m2"),
    BoqLine("6", "PRELIMINARIES", None, None),
    BoqLine("6.1", "Mobilisation and demobilisation", "ls", 1.0, None, "not_verifiable"),
    BoqLine("6.2", "Provisional sum for utilities diversion", "item", 1.0, None, "not_verifiable"),
]

# what the drawings carry that the BOQ does not (possible missed scope)
EXPECTED_MISSING_IN_BOQ = ["STORM-450 pipe run, 80 m (measured)"]
EXPECTED_CLASSES = {b.item_no: b.expected for b in BOQ if b.expected}

# accepted vendor quotes for the demo project: item_no -> [(vendor suffix, unit price, exclusion text or None)]
QUOTES: dict[str, list[tuple[str, float, str | None]]] = {
    "1.1": [("Gulf Earthmoving LLC", 17.5, None), ("Sanad Drainage Contracting", 19.0, None)],   # competing quotes
    "2.1": [("National Pipes Trading", 98.0, None)],
    "2.2": [("National Pipes Trading", 72.0, "Excludes testing and commissioning"), ],           # quote with an exclusion
    "2.3": [("Precast Arabia FZE", 4100.0, None)],
    "3.2": [("Khalifa Precast & Pavers", 41.0, None)],
    "4.1": [("Falcon Utilities LLC", 4300.0, None)],                                             # vendor whose prequalification lapsed
}


# ================================================================== history (15 past tenders)

@dataclass(slots=True)
class PastTender:
    code: str
    name: str
    outcome: str  # won | lost
    margin_on_sell_pct: float
    our_price: float
    winning_price: float
    lines: list[tuple[str, str, float, float]] = field(default_factory=list)  # (description, uom, qty, direct unit cost)


def history() -> list[PastTender]:
    rng = random.Random(20260930)
    base = [(b.description, b.uom, b.qty or 1.0) for b in BOQ if b.uom and b.expected != "not_verifiable"]
    rates = {b.item_no: r for b, r in zip(BOQ, [0] * len(BOQ), strict=True)}
    del rates
    ref = {  # a plausible direct cost per BOQ item, around which each past tender varies
        "1.1": 18.0, "1.2": 3.6, "1.3": 62.0, "2.1": 95.0, "2.2": 71.0, "2.3": 4000.0, "2.4": 2600.0, "3.1": 46.0,
        "3.2": 42.0, "3.3": 6.8, "3.4": 190.0, "4.1": 4500.0, "4.2": 46.0, "5.1": 9.5, "5.2": 1350.0, "5.3": 24.0,
    }
    items = [b for b in BOQ if b.item_no in ref]
    out: list[PastTender] = []
    margins = [5.2, 5.8, 6.4, 6.9, 7.3, 7.6, 8.1, 8.4, 8.8, 9.2, 9.6, 10.4, 11.0, 7.0, 8.0]
    # lower margins tend to win, higher ones lose on price -- a pattern the markup advice can cite
    for i, m in enumerate(margins, start=1):
        lines = []
        for b in rng.sample(items, k=rng.randint(7, len(items))):
            lines.append((b.description, b.uom or "nr", round((b.qty or 1) * rng.uniform(0.6, 1.4), 2), round(ref[b.item_no] * rng.uniform(0.92, 1.1), 2)))
        won = m < 8.2 or (m < 9.0 and i % 3 == 0)
        price = round(rng.uniform(2.5e6, 24e6), -3)
        winning = price if won else round(price * rng.uniform(0.94, 0.985), -3)
        out.append(PastTender(f"{HISTORY_PROJECT_PREFIX}{i:02d}", f"Past tender {i:02d} (synthetic)", "won" if won else "lost", m, price, winning, lines))
    assert base
    return out


# ================================================================== the tender pack (files)

def _dxf_road_and_drainage() -> bytes:
    import ezdxf

    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    for name in ("ROAD-CL", "ROAD-L", "ROAD-R", "SEWER-300", "SEWER-150", "STORM-450", "MANHOLE", "TEXT", "KERB"):
        if name not in doc.layers:
            doc.layers.add(name)
    blk = doc.blocks.new(name="MH")
    blk.add_circle((0, 0), 0.6)
    msp = doc.modelspace()
    msp.add_line((0, 0), (520, 0), dxfattribs={"layer": "ROAD-CL"})
    msp.add_line((0, 7), (520, 7), dxfattribs={"layer": "ROAD-L"})
    msp.add_line((0, -7), (520, -7), dxfattribs={"layer": "ROAD-R"})
    # 300mm sewer: MH1-MH2 (100 m), MH2-MH3 (90 m), MH3-MH4 (56 m) = 246 m
    xs = [50, 150, 240, 296]
    for a, b in zip(xs, xs[1:], strict=False):
        msp.add_lwpolyline([(a, 20), (b, 20)], dxfattribs={"layer": "SEWER-300"})
    # 150mm sewer: two runs, 80 + 70 = 150 m (BOQ says 100 m)
    msp.add_lwpolyline([(50, -20), (130, -20)], dxfattribs={"layer": "SEWER-150"})
    msp.add_lwpolyline([(130, -20), (200, -20)], dxfattribs={"layer": "SEWER-150"})
    # storm drain the BOQ forgot: one 80 m run
    msp.add_lwpolyline([(300, 40), (380, 40)], dxfattribs={"layer": "STORM-450"})
    mh_points = [(50, 20), (150, 20), (240, 20), (296, 20), (50, -20), (130, -20), (200, -20), (300, 40), (380, 40), (420, 20), (450, 20), (480, 20)]
    for x, y in mh_points:
        msp.add_blockref("MH", (x, y), dxfattribs={"layer": "MANHOLE"})
    texts = [
        "DRAWING NO: C-101", "REV: B", "SCALE 1:500", "TITLE: ROAD AND DRAINAGE PLAN", "DISCIPLINE: CIVIL",
        "LEGEND: PROPOSED 300mm uPVC SN8 SEWER", "LEGEND: PROPOSED 150mm uPVC SN8 SEWER", "LEGEND: PROPOSED 450mm STORM DRAIN",
        "100.0m 300mm uPVC SN8 SEWER (MH-01 TO MH-02)", "90.0m 300mm uPVC SN8 SEWER (MH-02 TO MH-03)", "56.0m 300mm uPVC SN8 SEWER (MH-03 TO MH-04)",
        "12 nos PRECAST MANHOLE 1200mm (SEE SCHEDULE)", "KERB L=1,040.0m PRECAST CONCRETE KERB TYPE A 300x150",
        "EXCAVATION 12,480 m3 (ROADWAY)", "ASPHALT WEARING COURSE 50mm 7,300 m2",
        "MH-01  IL 12.35  1200", "MH-02  IL 12.10  1200", "MH-03  IL 11.85  1200",
    ]
    for i, t in enumerate(texts):
        msp.add_text(t, dxfattribs={"insert": (10, -60 - i * 4), "height": 2.5, "layer": "TEXT"})
    # saved to a real file and CRLF-terminated, like a DXF from any CAD package (the harvester guards that path)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "c101.dxf"
        doc.saveas(path)
        data = path.read_bytes()
    return data if b"\r\n" in data else data.replace(b"\n", b"\r\n")


def _pdf_landscape() -> bytes:
    from reportlab.lib.pagesizes import A1, landscape
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A1), invariant=1)
    c.setFont("Helvetica", 14)
    lines = [
        "DRAWING NO: L-201", "REV: A", "SCALE 1:200", "TITLE: LANDSCAPE PLAN", "DISCIPLINE: LANDSCAPE",
        "LEGEND: PROPOSED GHAF TREE", "LEGEND: PROPOSED TURF", "TOPSOIL 4,200 m2 (200mm THICK)", "TURF 3,100 m2",
        "TREES 46 nos GHAF 2.5m HEIGHT",
    ]
    y = 2200
    for ln in lines:
        c.drawString(120, y, ln)
        y -= 40
    for i in range(30):  # some vector linework so the sheet reads as a drawing
        c.line(120, 1000 + i * 10, 1900, 1000 + i * 10 + (i % 5) * 4)
    c.showPage()
    c.save()
    return buf.getvalue()


def _boq_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    ws["A1"] = "AL REEM PACKAGE 3 - BILL OF QUANTITIES"
    ws["A2"] = "All rates in AED. Rates and amounts to be completed by the Tenderer."
    ws.append([])
    ws.append(["Item", "Description", "Unit", "Qty", "Rate", "Amount"])
    for b in BOQ:
        ws.append([b.item_no, b.description, b.uom, b.qty, None, None])
    ws.column_dimensions["B"].width = 80
    wb.properties.creator = "synthetic"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _boq_pdf_with_scanned_page() -> bytes:
    from pypdf import PdfReader, PdfWriter

    from app.demo.boq_pdf import BoqItem, build_boq_pdf, build_scanned_pdf

    items = [BoqItem(b.item_no, b.description, b.uom, b.qty, None) for b in BOQ[:16]]
    scanned_items = [BoqItem(b.item_no, b.description, b.uom, b.qty, None) for b in BOQ[16:]]
    writer = PdfWriter()
    for part in (build_boq_pdf(items, title="BILL OF QUANTITIES", collection=True), build_scanned_pdf(scanned_items)):
        for page in PdfReader(io.BytesIO(part)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build_pack() -> dict[str, bytes]:
    """path -> bytes. Deterministic. Folder names are a classification signal on purpose."""
    from app.intake.sample_pack import _text_pdf

    files = {
        f"{PACK_ROOT}/01 Drawings/C-101 Road and Drainage Plan Rev B.dxf": _dxf_road_and_drainage(),
        f"{PACK_ROOT}/01 Drawings/L-201 Landscape Plan Rev A.pdf": _pdf_landscape(),
        f"{PACK_ROOT}/02 BOQ/BOQ Rev 0.xlsx": _boq_xlsx(),
        f"{PACK_ROOT}/02 BOQ/BOQ Rev 0 (print copy).pdf": _boq_pdf_with_scanned_page(),
        f"{PACK_ROOT}/03 Specifications/Particular Specification.pdf": _text_pdf(
            ["PARTICULAR SPECIFICATION", "SECTION 02 21 00 EXCAVATION AND EARTHWORKS", "PART 1 - GENERAL", "1.1 Scope of work"] + ["Clause text."] * 20),
        f"{PACK_ROOT}/04 Addenda/Addendum No 1.pdf": _text_pdf(
            ["ADDENDUM No. 1", "The following amends the tender documents:", "Drawing C-101 is reissued at Revision B."]),
        f"{PACK_ROOT}/05 Contract/Conditions of Contract.pdf": _text_pdf(
            ["CONDITIONS OF CONTRACT", "PARTICULAR CONDITIONS", "Sub-Clause 1.1 Definitions"] + ["Clause text."] * 20),
    }
    return files


EXPECTED_CLASSIFICATION = {
    "C-101 Road and Drainage Plan Rev B.dxf": "drawing",
    "L-201 Landscape Plan Rev A.pdf": "drawing",
    "BOQ Rev 0.xlsx": "boq",
    "BOQ Rev 0 (print copy).pdf": "boq",
    "Particular Specification.pdf": "specification",
    "Addendum No 1.pdf": "addendum",
    "Conditions of Contract.pdf": "contract",
}


def write_pack(out_dir: str) -> list[str]:
    from pathlib import Path

    written = []
    for rel, data in build_pack().items():
        target = Path(out_dir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(str(target))
    return written


def cert_dates(spec: VendorSpec, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return today - timedelta(days=365 - max(spec.cert_days, -300)), today + timedelta(days=spec.cert_days)


def as_dict() -> dict[str, Any]:
    return {"cost_items": len(COST_LIBRARY), "vendors": len(VENDORS), "history": len(history()), "boq_lines": len(BOQ)}
