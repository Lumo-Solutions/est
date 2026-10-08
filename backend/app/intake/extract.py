"""Text/structure extraction feeding stage 1 rules and the stage 2 prompt.

Deliberately bounded: first 3 PDF pages, first 40 spreadsheet rows, first
20k chars of a docx, first 500 DXF text entities. Nothing here talks to the
network or to S3; bytes in, ``DocContent`` out.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field

from app.takeoff.pdf import PDFIUM_LOCK  # PDFium is not thread-safe: one use at a time, process-wide

MAX_PDF_PAGES_READ = 3
# A page with more than this many drawing objects is a CAD export. pdfplumber builds a Python object for every one of
# them (a real 8 MB single-sheet A0 drawing with 750,000 of them took 163 s and 3 GB), so such a file is read with
# PDFium, which parses the same page in about a second. Below it, pdfplumber is used as always (same text, same cache keys).
HEAVY_PDF_OBJECTS = 20_000
MAX_SHEET_ROWS = 40
MAX_TEXT_CHARS = 20_000
MAX_DXF_TEXT_ENTITIES = 500
# Below this many characters across the read pages a PDF is treated as having no text layer.
RASTER_CHAR_THRESHOLD = 20

_HEADER_GROUPS: dict[str, tuple[str, ...]] = {
    "item": ("item", "item no", "item no.", "item number", "item ref", "ref", "no", "no.", "s/n", "sn", "s.no"),
    "description": ("description", "desc", "item description", "work item", "particulars", "work description"),
    "unit": ("unit", "uom", "u.o.m", "unit of measure"),
    "qty": ("qty", "quantity", "qnty", "qty."),
    "rate": ("rate", "unit rate", "unit price", "price"),
    "amount": ("amount", "total", "value", "total amount"),
}


@dataclass(slots=True)
class SheetInfo:
    name: str
    header_row: int | None = None  # 1-based
    header_score: int = 0
    columns: list[str] = field(default_factory=list)
    # (column letter, header text) for the detected header row, in sheet order.
    header_cells: list[tuple[str, str]] = field(default_factory=list)
    sample_text: str = ""


@dataclass(slots=True)
class DocContent:
    filename: str
    ext: str
    sniffed: str | None
    text: str = ""
    page_texts: list[str] = field(default_factory=list)
    title_block_text: str = ""
    pages: int | None = None
    has_text_layer: bool = False
    is_raster: bool = False
    vector_density: int = 0
    sheets: list[SheetInfo] = field(default_factory=list)
    dxf_layers: list[str] = field(default_factory=list)
    # True when the stage 2 model should look at an image because there is no text to read.
    needs_image: bool = False
    error: str | None = None

    @property
    def best_sheet(self) -> SheetInfo | None:
        scored = [s for s in self.sheets if s.header_row is not None]
        return max(scored, key=lambda s: s.header_score) if scored else None


def _norm_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower()) if value is not None else ""


def detect_header(rows: list[list[object]]) -> tuple[int | None, int, list[str]]:
    """(1-based header row, score, columns) for the row matching most BOQ column groups."""
    best_row, best_score, best_cols = None, 0, []
    for idx, row in enumerate(rows, start=1):
        cells = [_norm_cell(c) for c in row]
        matched = {g for g, words in _HEADER_GROUPS.items() if any(c in words for c in cells)}
        score = len(matched)
        if score > best_score:
            best_row, best_score, best_cols = idx, score, [str(c).strip() for c in row if c is not None and str(c).strip()]
    if best_score < 3:
        return None, best_score, []
    return best_row, best_score, best_cols


def header_cells_of(row: list[object]) -> list[tuple[str, str]]:
    from openpyxl.utils import get_column_letter

    return [(get_column_letter(i), str(c).strip()) for i, c in enumerate(row, start=1) if c is not None and str(c).strip()]


def _pdf_is_heavy(data: bytes) -> bool:
    """True when any of the pages that are read has more than HEAVY_PDF_OBJECTS drawing objects. Counting stops at the
    threshold, so this costs about as much as opening the file."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(data)
        try:
            for i in range(min(len(doc), MAX_PDF_PAGES_READ)):
                page = doc[i]
                try:
                    n = 0
                    for _ in page.get_objects():
                        n += 1
                        if n > HEAVY_PDF_OBJECTS:
                            return True
                finally:
                    page.close()
            return False
        finally:
            doc.close()


def _extract_pdf_pdfium(data: bytes, content: DocContent) -> None:
    """The same fields as `_extract_pdf`, read with PDFium: for CAD exports that pdfplumber cannot afford."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(data)
        try:
            content.pages = len(doc)
            for i in range(min(len(doc), MAX_PDF_PAGES_READ)):
                page = doc[i]
                try:
                    textpage = page.get_textpage()
                    try:
                        content.page_texts.append(textpage.get_text_range() or "")
                        if i == 0:
                            w, h = page.get_size()
                            # Bottom-right region, as for pdfplumber below (PDF coordinates start at the bottom left).
                            content.title_block_text = textpage.get_text_bounded(left=w * 0.65, bottom=0, right=w, top=h * 0.30) or ""
                    finally:
                        textpage.close()
                    if i == 0:
                        content.vector_density = HEAVY_PDF_OBJECTS  # at least this many: it is dense
                finally:
                    page.close()
        finally:
            doc.close()
    content.text = "\n".join(content.page_texts)[:MAX_TEXT_CHARS]
    total = sum(len(t.strip()) for t in content.page_texts)
    content.has_text_layer = total >= RASTER_CHAR_THRESHOLD
    content.is_raster = not content.has_text_layer
    content.needs_image = content.is_raster


def _extract_pdf(data: bytes, content: DocContent) -> None:
    import pdfplumber

    if _pdf_is_heavy(data):
        _extract_pdf_pdfium(data, content)
        return
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        content.pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages[:MAX_PDF_PAGES_READ]):
            text = page.extract_text() or ""
            content.page_texts.append(text)
            if i == 0:
                content.vector_density = len(page.lines) + len(page.rects) + len(page.curves)
                w, h = float(page.width), float(page.height)
                # Bottom-right region, same proportions as app/takeoff/pdf.py's title block crop.
                box = (w * 0.65, h * 0.70, w, h)
                try:
                    content.title_block_text = page.crop(box).extract_text() or ""
                except Exception:  # noqa: BLE001 -- a bad crop must not fail classification
                    content.title_block_text = ""
    content.text = "\n".join(content.page_texts)[:MAX_TEXT_CHARS]
    total = sum(len(t.strip()) for t in content.page_texts)
    content.has_text_layer = total >= RASTER_CHAR_THRESHOLD
    content.is_raster = not content.has_text_layer
    content.needs_image = content.is_raster


def _extract_dxf(data: bytes, content: DocContent) -> None:
    from app.takeoff.dxf import _read_dxf_document

    doc = _read_dxf_document(data)
    content.dxf_layers = sorted(layer.dxf.name for layer in doc.layers)
    texts: list[str] = []
    for entity in doc.modelspace():
        if len(texts) >= MAX_DXF_TEXT_ENTITIES:
            break
        kind = entity.dxftype()
        if kind == "TEXT":
            texts.append(entity.dxf.text)
        elif kind == "MTEXT":
            texts.append(entity.plain_text())
        elif kind == "INSERT":
            texts.extend(str(a.dxf.text) for a in entity.attribs)
    content.text = "\n".join(t for t in texts if t)[:MAX_TEXT_CHARS]
    content.title_block_text = content.text
    content.has_text_layer = bool(content.text.strip())


def _extract_xlsx(data: bytes, content: DocContent) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        chunks: list[str] = []
        for ws in wb.worksheets[:6]:
            rows: list[list[object]] = []
            for row in ws.iter_rows(min_row=1, max_row=MAX_SHEET_ROWS, values_only=True):
                rows.append(list(row))
            header_row, score, cols = detect_header(rows)
            sample = "\n".join(" | ".join(str(c) for c in r if c is not None) for r in rows[:12])
            content.sheets.append(
                SheetInfo(ws.title, header_row, score, cols, header_cells_of(rows[header_row - 1]) if header_row else [], sample)
            )
            chunks.append(f"[{ws.title}]\n{sample}")
        content.text = "\n".join(chunks)[:MAX_TEXT_CHARS]
        content.has_text_layer = bool(content.text.strip())
    finally:
        wb.close()


def _extract_csv(data: bytes, content: DocContent) -> None:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_SHEET_ROWS:
            break
        rows.append(row)
    header_row, score, cols = detect_header(rows)
    content.sheets.append(
        SheetInfo(
            "csv", header_row, score, cols,
            header_cells_of(rows[header_row - 1]) if header_row else [],
            "\n".join(",".join(r) for r in rows[:12]),
        )
    )
    content.text = text[:MAX_TEXT_CHARS]
    content.has_text_layer = bool(text.strip())


def _extract_docx(data: bytes, content: DocContent) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml")
    # Paragraph ends become newlines, every other tag disappears.
    text = re.sub(r"</w:p>", "\n", xml.decode("utf-8", errors="replace"))
    text = re.sub(r"<[^>]+>", "", text)
    content.text = text[:MAX_TEXT_CHARS]
    content.has_text_layer = bool(text.strip())


def extract_content(*, filename: str, ext: str, sniffed: str | None, data: bytes) -> DocContent:
    """Never raises: an unreadable file becomes an empty DocContent with ``error`` set,
    so classification falls back to filename rules and a human still sees it."""
    content = DocContent(filename=filename, ext=ext, sniffed=sniffed)
    try:
        if ext == "pdf":
            _extract_pdf(data, content)
        elif ext == "dxf":
            _extract_dxf(data, content)
        elif ext == "xlsx":
            _extract_xlsx(data, content)
        elif ext == "csv":
            _extract_csv(data, content)
        elif ext == "docx":
            _extract_docx(data, content)
        elif ext in ("jpg", "jpeg", "png"):
            content.is_raster = True
            content.needs_image = True
        # xls / doc / dwg: no parser; stored, classified from filename/extension only.
    except Exception as exc:  # noqa: BLE001
        content.error = f"{type(exc).__name__}: {exc}"[:300]
    return content
