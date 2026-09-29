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

MAX_PDF_PAGES_READ = 3
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


def _extract_pdf(data: bytes, content: DocContent) -> None:
    import pdfplumber

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
            content.sheets.append(SheetInfo(ws.title, header_row, score, cols, sample))
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
    content.sheets.append(SheetInfo("csv", header_row, score, cols, "\n".join(",".join(r) for r in rows[:12])))
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
