"""Deterministic PDF Bill-of-Quantities reader (docs/ai-plan.md §5).

pdfplumber word positions -> columns (from the header row, remembered across
pages when the header is not repeated) -> rows. Handles: repeated headers,
wrapped descriptions, brought/carried-forward lines, collection/summary pages,
section headings with no quantity. A page it cannot read cleanly, or one with
no text layer (a scan), is reported as ``needs_ai`` so the caller can hand just
that page to the vision task. Nothing here calls a model.

Coordinates in ``bbox`` are PDF points from the page's top-left
(x0, top, x1, bottom); ``page_size`` lets the UI normalise them.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pdfplumber

LINE_TOLERANCE = 3.0
COLUMN_PAD = 14.0
CLEAN_PAGE_MIN_QUALITY = 0.7

# header vocabulary per column (lower-case words that may appear in the header cell)
_HEADER_WORDS: dict[str, set[str]] = {
    "item": {"item", "no", "no.", "ref", "ref.", "code", "nr"},
    "description": {"description", "particulars", "work", "details", "item description"},
    "unit": {"unit", "uom", "units"},
    "qty": {"qty", "qty.", "quantity", "quantities"},
    "rate": {"rate", "price", "unit rate"},
    "amount": {"amount", "total", "value", "extension"},
}
_NUMERIC_COLS = ("unit", "qty", "rate", "amount")

_ITEM_NO = re.compile(r"^(?:[A-Za-z]{1,2}[-.]?)?\d+(?:[.\-]\d+)*[A-Za-z]?$|^[A-Z]$")
_NUMBER = re.compile(r"^\(?-?[\d,]*\.?\d+\)?$")
_SKIP_DESCRIPTION = re.compile(
    r"brought\s+forward|carried\s+forward|\bb/?f\b|\bc/?f\b|carried\s+to\s+(?:collection|summary)|"
    r"to\s+collection|page\s+total|sub[-\s]?total|grand\s+total|total\s+carried",
    re.I,
)
_COLLECTION_PAGE = re.compile(r"\bcollection\b|\bsummary\b|\bgrand\s+summary\b", re.I)


@dataclass(slots=True)
class PdfBoqRow:
    page: int
    item_no: str | None
    description: str
    uom: str | None
    quantity: float | None
    quantity_raw: str | None
    rate_raw: str | None
    amount_raw: str | None
    bbox: list[float]
    page_size: list[float]
    source: str = "table"  # table | ai
    confidence: float = 0.9


@dataclass(slots=True)
class PageResult:
    page: int  # 1-based
    status: str  # table | skipped_collection | needs_ai | empty
    rows: list[PdfBoqRow] = field(default_factory=list)
    note: str = ""
    quality: float = 0.0


@dataclass(slots=True)
class _Columns:
    item: tuple[float, float] | None
    unit: tuple[float, float] | None
    qty: tuple[float, float] | None
    rate: tuple[float, float] | None
    amount: tuple[float, float] | None
    desc_start: float
    desc_end: float


def _lines(words: list[dict]) -> list[list[dict]]:
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _header_columns(line: list[dict]) -> _Columns | None:
    """A header line has words from >=3 distinct column groups, including
    description and one of qty/amount."""
    found: dict[str, tuple[float, float]] = {}
    for w in line:
        t = _norm(w["text"])
        for group, vocab in _HEADER_WORDS.items():
            if group == "description":
                hit = t in vocab
            else:
                hit = t in vocab
            if hit and group not in found:
                found[group] = (w["x0"], w["x1"])
                break
    if "description" not in found or len(found) < 3 or not ({"qty", "amount", "rate"} & set(found)):
        return None
    numeric_starts = [found[c][0] for c in _NUMERIC_COLS if c in found]
    desc_start = found["description"][0] - COLUMN_PAD
    desc_end = (min(numeric_starts) - COLUMN_PAD) if numeric_starts else 10_000.0
    return _Columns(
        item=found.get("item"), unit=found.get("unit"), qty=found.get("qty"), rate=found.get("rate"),
        amount=found.get("amount"), desc_start=desc_start, desc_end=desc_end,
    )


def _assign(word: dict, cols: _Columns) -> str:
    cx = (word["x0"] + word["x1"]) / 2
    best, best_dist = None, 1e9
    for name in ("item", "unit", "qty", "rate", "amount"):
        span = getattr(cols, name)
        if span is None:
            continue
        lo, hi = span[0] - COLUMN_PAD, span[1] + COLUMN_PAD
        if lo <= cx <= hi:
            dist = abs(cx - (span[0] + span[1]) / 2)
            if dist < best_dist:
                best, best_dist = name, dist
    if best:
        return best
    if cols.item is not None and cx < cols.desc_start:
        return "item"
    return "description"


def _to_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    t = raw.strip().replace(",", "")
    if not t or not _NUMBER.match(t):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _title_says_collection(lines: list[list[dict]]) -> bool:
    head = " ".join(" ".join(w["text"] for w in line) for line in lines[:4])
    return bool(_COLLECTION_PAGE.search(head)) and not re.search(r"\bunit\b", head, re.I)


def _cells_of(line: list[dict], cols: _Columns) -> dict[str, str]:
    cells: dict[str, list[str]] = {}
    for w in line:
        cells.setdefault(_assign(w, cols), []).append(w["text"])
    return {k: " ".join(v).strip() for k, v in cells.items()}


def _line_bbox(line: list[dict]) -> list[float]:
    return [min(w["x0"] for w in line), min(w["top"] for w in line), max(w["x1"] for w in line), max(w["bottom"] for w in line)]


def _merge_bbox(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def read_pdf_boq(data: bytes, *, max_pages: int = 400) -> list[PageResult]:
    results: list[PageResult] = []
    carried: _Columns | None = None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for index, page in enumerate(pdf.pages[:max_pages], start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=2, y_tolerance=2)
            if not words:
                results.append(PageResult(index, "needs_ai", note="no text layer (scanned page)"))
                continue
            lines = _lines(words)
            if _title_says_collection(lines):
                results.append(PageResult(index, "skipped_collection", note="collection / summary page"))
                continue

            cols, start = carried, 0
            for i, line in enumerate(lines):
                header = _header_columns(line)
                if header is not None:
                    cols, start = header, i + 1
                    carried = header
                    break
            else:
                # No header on this page: continue with the last page's columns if any.
                if cols is None:
                    results.append(PageResult(index, "needs_ai", note="no BOQ table header found"))
                    continue
                start = _first_data_line(lines, cols)

            size = [float(page.width), float(page.height)]
            rows = _rows_from_lines(lines[start:], cols, index, size)
            quality = _quality(rows)
            if not rows:
                results.append(PageResult(index, "empty", note="no BOQ rows on this page", quality=0.0))
            elif quality < CLEAN_PAGE_MIN_QUALITY:
                results.append(PageResult(index, "needs_ai", note=f"table unclear (quality {quality:.2f})", quality=quality))
            else:
                results.append(PageResult(index, "table", rows=rows, quality=quality))
    return results


def _first_data_line(lines: list[list[dict]], cols: _Columns) -> int:
    """On a page without its own header, skip the page title / running head: the
    first line that starts a row (numbered item, or unit + numbers) is where data begins."""
    for i, line in enumerate(lines):
        cells = _cells_of(line, cols)
        item = cells.get("item", "")
        has_numbers = any(cells.get(c) for c in ("qty", "rate", "amount"))
        if (item and _ITEM_NO.match(item)) or (cells.get("unit") and has_numbers):
            return i
    return len(lines)


def _rows_from_lines(lines: list[list[dict]], cols: _Columns, page: int, size: list[float]) -> list[PdfBoqRow]:
    rows: list[PdfBoqRow] = []
    current: PdfBoqRow | None = None
    for line in lines:
        # A repeated header mid-page (some exports repeat it per section) is not a row.
        if _header_columns(line) is not None:
            continue
        cells = _cells_of(line, cols)
        desc = cells.get("description", "")
        item = cells.get("item", "")
        has_numbers = any(cells.get(c) for c in ("qty", "rate", "amount"))
        if _SKIP_DESCRIPTION.search(desc) or _SKIP_DESCRIPTION.search(item):
            current = None
            continue
        if not desc and not item and not has_numbers and not cells.get("unit"):
            continue
        starts_row = bool(item and _ITEM_NO.match(item)) or (bool(cells.get("unit")) and has_numbers and bool(desc))
        if not starts_row and current is not None and desc and not has_numbers and not cells.get("unit"):
            # wrapped description line
            current.description = f"{current.description} {desc}".strip()
            current.bbox = _merge_bbox(current.bbox, _line_bbox(line))
            continue
        if not starts_row and not desc:
            continue
        qty_raw = cells.get("qty") or None
        current = PdfBoqRow(
            page=page, item_no=item or None, description=desc, uom=(cells.get("unit") or None),
            quantity=_to_number(qty_raw), quantity_raw=qty_raw, rate_raw=cells.get("rate") or None,
            amount_raw=cells.get("amount") or None, bbox=_line_bbox(line), page_size=size,
        )
        rows.append(current)
    return rows


def _quality(rows: list[PdfBoqRow]) -> float:
    """Share of rows that look like well-formed BOQ lines: a heading (item + text, no numbers),
    or a description with a parseable quantity and a unit."""
    if not rows:
        return 0.0
    good = 0
    for r in rows:
        heading = r.item_no and r.description and not r.uom and r.quantity_raw is None and r.amount_raw is None
        line = r.description and r.uom and r.quantity is not None
        if heading or line:
            good += 1
    return good / len(rows)
