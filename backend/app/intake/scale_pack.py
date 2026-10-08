"""A synthetic tender folder at production scale (docs/intake-scale/report.md): thousands of files of mixed kinds and
sizes, including multi-page A0/A1 drawings, scans, 50-100 MB PDFs, duplicates, junk and zips, written to disk with a
manifest of what each file is. Deterministic for a given seed. Memory-bounded: big files are streamed to disk in
chunks, nothing is held whole except the small ones.

    python -m app.intake.scale_pack /data/pack --files 2000 --seed 7

The generated text carries exactly the cues the mock AI provider keys on (title blocks, headings), so a run on the
mock provider has a known right answer: `manifest.json` lists `expected_class` for every file.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

MB = 1024 * 1024
_CHUNK = 4 * MB

DISCIPLINES = [
    ("Roads", "ROAD LAYOUT PLAN", "roads_civil"),
    ("Stormwater", "STORMWATER DRAINAGE PLAN", "stormwater"),
    ("Sewer", "SEWER NETWORK PLAN AND PROFILE", "sewer"),
    ("Water", "WATER SUPPLY NETWORK LAYOUT", "water_supply"),
    ("Lighting", "STREET LIGHTING LAYOUT", "electrical_lighting"),
    ("Landscape", "LANDSCAPE PLANTING PLAN", "landscape"),
    ("Structure", "STRUCTURAL FOUNDATION PLAN", "structural"),
    ("Architecture", "ARCHITECTURAL FLOOR PLAN", "architectural"),
]
PAGE_SIZES = {"A4": (595, 842), "A3": (842, 1191), "A1": (1684, 2384), "A0": (2384, 3370)}

TEXT_DOCS = [
    ("specification", "Specifications", ["SECTION 03 30 00 CAST-IN-PLACE CONCRETE", "PART 1 GENERAL", "1.1 SUMMARY"]),
    ("contract", "Contract", ["CONDITIONS OF CONTRACT", "FIDIC Red Book 2017", "PARTICULAR CONDITIONS"]),
    ("tender_instructions", "Tender", ["INSTRUCTIONS TO TENDERERS", "1. Submission deadline"]),
    ("tender_forms", "Tender", ["FORM OF TENDER", "BID BOND", "Name of tenderer"]),
    ("clarification", "Clarifications", ["REQUEST FOR INFORMATION", "RFI No. {n}", "Response to query"]),
    ("site_investigation", "Site Investigation", ["GEOTECHNICAL INVESTIGATION REPORT", "Borehole logs", "Soil investigation"]),
    ("correspondence", "Correspondence", ["Dear Sirs,", "Further to our letter of {n} March", "Yours faithfully"]),
]


@dataclass
class Item:
    path: str  # relative path inside the pack
    expected_class: str | None
    kind: str
    size: int = 0
    note: str = ""
    extra: dict = field(default_factory=dict)


def _esc(s: str) -> bytes:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")


class _PdfFile:
    """Streams a PDF to a file handle: text and vector linework per page, optionally one raw RGB image per page."""

    def __init__(self, fh) -> None:
        self.fh = fh
        self.offsets: dict[int, int] = {}
        self.fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    def _obj(self, n: int, body: bytes) -> None:
        self.offsets[n] = self.fh.tell()
        self.fh.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")

    def build(self, pages: list[dict], rng: random.Random) -> None:
        # 1 catalog, 2 pages, 3 font; then per page: page, contents, [image]
        num = 4
        page_ids: list[int] = []
        for spec in pages:
            w, h = spec["size"]
            content = bytearray()
            lines = spec.get("lines", 0)
            if lines:
                content += b"q 0.4 w\n"
                for _ in range(lines):
                    x, y = rng.randrange(0, w), rng.randrange(0, h)
                    content += b"%d %d m %d %d l S\n" % (x, y, x + rng.randrange(-90, 90), y + rng.randrange(-90, 90))
                content += b"Q\n"
            for x, y, size, text in spec.get("text", []):
                content += b"BT /F1 %d Tf %d %d Td (" % (size, x, y) + _esc(text) + b") Tj ET\n"
            image = spec.get("image")  # (width, height) raw 8-bit RGB
            page_id, content_id, image_id = num, num + 1, num + 2
            num += 3 if image else 2
            if image:
                iw, ih = image
                content += b"q %d 0 0 %d 0 0 cm /Im1 Do Q\n" % (w, h)
            self._obj(content_id, b"<< /Length %d >>\nstream\n" % len(content) + bytes(content) + b"\nendstream")
            xobj = b" /XObject << /Im1 %d 0 R >>" % image_id if image else b""
            self._obj(
                page_id,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >>%s >> >>" % (w, h, content_id, xobj),
            )
            if image:
                self.offsets[image_id] = self.fh.tell()
                length = iw * ih * 3
                self.fh.write(
                    f"{image_id} 0 obj\n<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length {length} >>\nstream\n".encode()
                )
                left = length
                while left > 0:
                    n = min(_CHUNK, left)
                    self.fh.write(rng.randbytes(n))
                    left -= n
                self.fh.write(b"\nendstream\nendobj\n")
            page_ids.append(page_id)
        self._obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = b" ".join(b"%d 0 R" % p for p in page_ids)
        self._obj(2, b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids))
        self._obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        xref = self.fh.tell()
        total = num
        out = [b"xref\n0 %d\n0000000000 65535 f \n" % total]
        for i in range(1, total):
            out.append(b"%010d 00000 n \n" % self.offsets.get(i, 0))
        out.append(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref))
        self.fh.write(b"".join(out))


def _write_pdf(path: Path, pages: list[dict], rng: random.Random) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        _PdfFile(fh).build(pages, rng)
    return path.stat().st_size


def _drawing_pages(rng: random.Random, number: str, title: str, size_name: str, npages: int, lines: int, scan_mb: float = 0.0) -> list[dict]:
    w, h = PAGE_SIZES[size_name]
    pages = []
    for i in range(npages):
        sheet = f"{number}" if npages == 1 else f"{number}-{i + 1:02d}"
        block = [
            (int(w * 0.68), int(h * 0.12), 9, f"DRAWING NO: {sheet}"),
            (int(w * 0.68), int(h * 0.10), 9, "REV: A    SCALE: 1:500"),
            (int(w * 0.68), int(h * 0.08), 9, f"TITLE: {title}"),
            (int(w * 0.68), int(h * 0.06), 9, "PROJECT: SCALE-SIM TENDER"),
        ]
        spec: dict = {"size": (w, h), "lines": lines, "text": [(int(w * 0.05), int(h * 0.95), 14, title), *block]}
        if scan_mb:
            side = int((scan_mb * MB / 3) ** 0.5)
            spec["image"] = (side, side)
            spec["text"] = []  # a scan has no text layer
            spec["lines"] = 0
        pages.append(spec)
    return pages


def _text_pages(rng: random.Random, heading: list[str], npages: int, n: int) -> list[dict]:
    pages = []
    for p in range(npages):
        lines = [(60, 780, 16, heading[0].format(n=n))] if p == 0 else []
        y = 750
        for ln in heading[1:] if p == 0 else []:
            lines.append((60, y, 11, ln.format(n=n)))
            y -= 18
        for _ in range(28):
            lines.append((60, y, 10, " ".join(rng.choice(_WORDS) for _ in range(12))))
            y -= 18
            if y < 60:
                break
        pages.append({"size": PAGE_SIZES["A4"], "text": lines})
    return pages


_WORDS = "the contractor shall provide all labour materials plant and equipment necessary for the works in accordance with drawings and specifications approved by engineer site level compact layer concrete pipe road kerb".split()


def _dxf_bytes(rng: random.Random, number: str, title: str, layer: str) -> bytes:
    import ezdxf

    doc = ezdxf.new("R2018")
    doc.layers.add(layer)
    msp = doc.modelspace()
    msp.add_text(f"DRAWING NO: {number}", dxfattribs={"layer": layer, "height": 2.5, "insert": (0, 0)})
    msp.add_text(f"TITLE: {title}", dxfattribs={"layer": layer, "height": 2.5, "insert": (0, -4)})
    msp.add_text("REV: A  SCALE: 1:500", dxfattribs={"layer": layer, "height": 2.5, "insert": (0, -8)})
    for _ in range(rng.randrange(40, 400)):
        x, y = rng.uniform(0, 500), rng.uniform(0, 300)
        msp.add_line((x, y), (x + rng.uniform(-20, 20), y + rng.uniform(-20, 20)), dxfattribs={"layer": layer})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _xlsx_bytes(rng: random.Random, n: int, kind: str) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    if kind == "boq":
        ws.title = "BOQ"
        ws.append(["Bills of Quantities", f"Package {n}"])
        ws.append([])
        ws.append(["Item No", "Description", "Unit", "Qty", "Rate", "Amount"])
        for i in range(1, rng.randrange(20, 200)):
            ws.append([f"{n}.{i}", f"Excavate and compact {rng.choice(_WORDS)} layer", rng.choice(["m3", "m2", "m", "nr"]), rng.randrange(1, 900), rng.randrange(5, 400), None])
    else:
        ws.title = "Programme"
        ws.append(["Programme", f"Baseline {n}"])
        ws.append(["Activity", "Start", "Finish", "Duration"])
        for i in range(rng.randrange(10, 80)):
            ws.append([f"Activity {i}", "2026-01-05", "2026-02-10", rng.randrange(3, 60)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _docx_bytes(rng: random.Random, heading: str, n: int) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{h}</w:t></w:r></w:p>" for h in [heading.format(n=n), *(" ".join(rng.choice(_WORDS) for _ in range(14)) for _ in range(60))])
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>"
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", doc)
    return out.getvalue()


def _small_pdf_bytes(rng: random.Random, pages: list[dict]) -> bytes:
    buf = io.BytesIO()
    _PdfFile(buf).build(pages, rng)
    return buf.getvalue()


def generate(out_dir: Path, files: int = 2000, seed: int = 7, huge: int = 12, progress=None) -> list[Item]:
    """Writes `files` files under out_dir/Tender and returns the manifest. Mix (as a share of `files`): about 28 %
    vector-PDF drawings (A4-A0, 1-8 pages), 2 % long drawing sets (30-60 pages, 8-35 MB), 2 % scanned drawings (3-30 MB),
    `huge` PDFs of 50-100 MB, 15 % DXF, 9 % BOQ, 11 % specs, 18 % other tender documents, 3 % addenda, 5 % duplicates,
    1 % junk and a few zips."""
    rng = random.Random(seed)
    root = out_dir / "Tender"
    root.mkdir(parents=True, exist_ok=True)
    items: list[Item] = []

    def add(rel: str, cls: str | None, kind: str, data: bytes | None = None, *, pages: list[dict] | None = None, note: str = "", **extra) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if pages is not None:
            size = _write_pdf(path, pages, rng)
        else:
            assert data is not None
            path.write_bytes(data)
            size = len(data)
        items.append(Item(f"Tender/{rel}", cls, kind, size, note, extra))
        if progress and len(items) % 100 == 0:
            progress(len(items))

    n_total = files
    n_huge = min(huge, max(0, files // 20))
    n_long = max(1, int(n_total * 0.02))
    n_scan = max(1, int(n_total * 0.02))
    n_vec = int(n_total * 0.28)
    n_dxf = int(n_total * 0.15)
    n_boq = int(n_total * 0.09)
    n_spec = int(n_total * 0.11)
    n_add = int(n_total * 0.03)
    n_dup = int(n_total * 0.05)
    n_junk = max(8, int(n_total * 0.01))
    n_zip = max(2, int(n_total * 0.004))
    n_other = n_total - (n_huge + n_long + n_scan + n_vec + n_dxf + n_boq + n_spec + n_add + n_dup + n_junk + n_zip)

    def drawing_rel(ix: int, ext: str) -> tuple[str, str, str, str]:
        folder, title, disc = DISCIPLINES[ix % len(DISCIPLINES)]
        area = f"Area {1 + (ix // len(DISCIPLINES)) % 12:02d}"
        number = f"{folder[:1].upper()}-{100 + ix}"
        return f"Drawings/{folder}/{area}/{number} Rev A.{ext}", number, f"{title} {area}", disc

    for i in range(n_vec):
        rel, number, title, _ = drawing_rel(i, "pdf")
        size_name = rng.choices(["A4", "A3", "A1", "A0"], weights=[2, 4, 5, 3])[0]
        add(rel, "drawing", "vector_pdf", pages=_drawing_pages(rng, number, title, size_name, rng.randrange(1, 9), rng.randrange(500, 30_000)), page_size=size_name)
    for i in range(n_long):
        rel, number, title, _ = drawing_rel(n_vec + i, "pdf")
        rel = rel.replace("Rev A", "Set Rev A")
        add(rel, "drawing", "long_drawing_set", pages=_drawing_pages(rng, number, title, rng.choice(["A1", "A3"]), rng.randrange(30, 61), rng.randrange(8_000, 40_000)))
    for i in range(n_scan):
        rel, number, title, _ = drawing_rel(n_vec + n_long + i, "pdf")
        add(rel.replace("Rev A", "Scan"), "drawing", "scanned_drawing", pages=_drawing_pages(rng, number, title, "A3", 1, 0, scan_mb=rng.uniform(3, 30)), note="no text layer: needs the vision model")
    for i in range(n_huge):
        rel, number, title, _ = drawing_rel(n_vec + n_long + n_scan + i, "pdf")
        mb = rng.uniform(52, 98)
        if i % 2 == 0:
            pages = _drawing_pages(rng, number, title, "A0", 1, 0, scan_mb=mb)
        else:
            pages = _drawing_pages(rng, number, title, "A1", 1, 0, scan_mb=mb)
        add(rel.replace("Rev A", "Full set"), None, "huge", pages=pages, note="over the processing limit: needs check, too large")
    for i in range(n_dxf):
        rel, number, title, disc = drawing_rel(i + 7, "dxf")
        add(rel, "drawing", "dxf", _dxf_bytes(rng, number, title, disc.upper()))
    for i in range(n_boq):
        kind = rng.choice(["xlsx", "xlsx", "csv", "pdf"])
        stem = f"BOQ/Package {i + 1:03d} Bills of Quantities"
        if kind == "xlsx":
            add(f"{stem}.xlsx", "boq", "boq_xlsx", _xlsx_bytes(rng, i + 1, "boq"))
        elif kind == "csv":
            rows = ["Item No,Description,Unit,Qty,Rate,Amount"] + [f"{i + 1}.{k},Excavate trench {rng.choice(_WORDS)},m3,{rng.randrange(1, 500)},{rng.randrange(5, 90)}," for k in range(1, rng.randrange(10, 80))]
            add(f"{stem}.csv", "boq", "boq_csv", "\n".join(rows).encode())
        else:
            add(f"{stem}.pdf", "boq", "boq_pdf", pages=_text_pages(rng, ["BILL OF QUANTITIES", "Preliminaries and general items", f"Package {i + 1}"], rng.randrange(1, 12), i))
    for i in range(n_spec):
        ext = "docx" if i % 5 == 0 else "pdf"
        rel = f"Specifications/Division {1 + i % 16:02d}/Spec Section {i + 1:03d}.{ext}"
        heading = ["SECTION 03 30 00 CAST-IN-PLACE CONCRETE", "PART 1 GENERAL", f"1.{i} SUMMARY"]
        if ext == "docx":
            add(rel, "specification", "spec_docx", _docx_bytes(rng, heading[0], i))
        else:
            add(rel, "specification", "spec_pdf", pages=_text_pages(rng, heading, rng.randrange(1, 40), i))
    for i in range(n_add):
        add(f"Addenda/Addendum {i + 1:02d}.pdf", "addendum", "addendum_pdf", pages=_text_pages(rng, [f"ADDENDUM No. {i + 1}", "Issue date: 3 April 2026", f"This addendum supersedes drawing R-{100 + i * 7} Rev A."], 2, i))
    for i in range(n_other):
        cls, folder, heading = TEXT_DOCS[1 + i % (len(TEXT_DOCS) - 1)]
        add(f"{folder}/{cls}_{i + 1:04d}.pdf", cls, f"{cls}_pdf", pages=_text_pages(rng, heading, rng.randrange(1, 11), i))
    for i in range(n_zip):
        members = []
        for k in range(rng.randrange(4, 14)):
            cls, folder, heading = TEXT_DOCS[(i + k) % len(TEXT_DOCS)]
            members.append((f"{folder}/zip{i}_{k}_{cls}.pdf", _small_pdf_bytes(rng, _text_pages(rng, heading, 2, i * 100 + k))))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in members:
                zf.writestr(name, payload)
        add(f"Transmittals/Transmittal {i + 1:02d}.zip", None, "zip", out.getvalue(), members=len(members))
    # junk: system files, unsupported types, macro workbooks, empty and corrupt files
    junk = [
        ("Misc/.DS_Store", b"\x00\x00\x00\x01Bud1", "system"),
        ("Misc/Thumbs.db", b"thumbs", "system"),
        ("Misc/installer.exe", b"MZ" + b"\x00" * 64, "unsupported"),
        ("Misc/macro.xlsm", b"PK\x03\x04macro", "macro"),
        ("Misc/empty.pdf", b"", "empty"),
        ("Misc/corrupt.pdf", b"%PDF-1.4\nthis is not a pdf at all", "corrupt"),
    ]
    for j in range(n_junk):
        name, data, why = junk[j % len(junk)]
        stem, dot, ext = name.rpartition(".")
        add(f"{stem}_{j}.{ext}" if dot else f"{name}_{j}", None, f"junk_{why}", data + (b"" if why in ("empty",) else bytes([j % 251])))
    # duplicates: byte-identical copies of earlier small files under other names/folders
    pool = [it for it in items if it.kind in ("vector_pdf", "dxf", "spec_pdf", "boq_xlsx") and it.size < 2 * MB]
    for i in range(min(n_dup, len(pool))):
        src = rng.choice(pool)
        data = (root.parent / src.path).read_bytes()
        add(f"Duplicates/Copy of {i + 1:03d} {Path(src.path).name}", src.expected_class, "duplicate", data, copy_of=src.path)
    while len(items) < files:  # rounding
        i = len(items)
        add(f"Correspondence/letter_{i:05d}.pdf", "correspondence", "correspondence_pdf", pages=_text_pages(rng, ["Dear Sirs,", "Further to our letter", "Yours faithfully"], 1, i))
    rng.shuffle(items)
    (out_dir / "manifest.json").write_text(
        json.dumps({"seed": seed, "files": len(items), "total_bytes": sum(i.size for i in items), "items": [i.__dict__ for i in items]}, indent=1)
    )
    return items


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(MB), b""):
            h.update(block)
    return h.hexdigest()


def iter_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a synthetic production-scale tender folder.")
    ap.add_argument("out", type=Path)
    ap.add_argument("--files", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--huge", type=int, default=12)
    args = ap.parse_args()
    items = generate(args.out, args.files, args.seed, args.huge, progress=lambda n: print(f"{n} files", flush=True))
    kinds: dict[str, int] = {}
    for it in items:
        kinds[it.kind] = kinds.get(it.kind, 0) + 1
    print(json.dumps({"files": len(items), "bytes": sum(i.size for i in items), "kinds": kinds}, indent=1))


if __name__ == "__main__":
    main()
