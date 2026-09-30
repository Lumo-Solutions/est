"""Synthetic BOQ PDFs for tests and the AI demo dataset (never real tender data).

`build_boq_pdf` lays a bill out like a real UAE infrastructure BOQ: a header
row (optionally repeated per page), wrapped descriptions, section headings,
"brought forward / carried forward" lines and a collection page. `build_scanned_pdf`
renders the same rows as an image-only page (no text layer) to exercise the
vision fallback. Output is deterministic for the same input.
"""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BoqItem:
    item_no: str
    description: str
    unit: str | None = None
    qty: float | None = None
    rate: float | None = None

    @property
    def is_heading(self) -> bool:
        return self.unit is None and self.qty is None


X_ITEM, X_DESC, X_UNIT, X_QTY, X_RATE, X_AMOUNT = 40, 95, 405, 490, 540, 585
DESC_WRAP = 52
TOP, LINE_H, LINES_PER_PAGE = 780, 12, 46


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:,.2f}"


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, DESC_WRAP) or [""]


def _pages(items: list[BoqItem]) -> list[list[tuple[str, BoqItem | None, int]]]:
    """Lay items out into pages of drawable lines: (kind, item, wrap_index)."""
    pages: list[list[tuple[str, BoqItem | None, int]]] = [[]]
    used = 0
    for it in items:
        need = len(_wrap(it.description))
        if used + need > LINES_PER_PAGE - 6:
            pages.append([])
            used = 0
        for w in range(need):
            pages[-1].append(("row", it, w))
        used += need
    return pages


def build_boq_pdf(
    items: list[BoqItem], *, title: str = "BILL OF QUANTITIES", repeat_header: bool = True, collection: bool = True
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(title)
    pages = _pages(items)
    running = 0.0
    for p_index, lines in enumerate(pages):
        y = TOP
        c.setFont("Helvetica-Bold", 12)
        c.drawString(X_ITEM, y, title if p_index == 0 else f"{title} (continued)")
        y -= 22
        if p_index == 0 or repeat_header:
            c.setFont("Helvetica-Bold", 9)
            for x, label, right in (
                (X_ITEM, "Item", False), (X_DESC, "Description", False), (X_UNIT, "Unit", False),
                (X_QTY, "Qty", True), (X_RATE, "Rate", True), (X_AMOUNT, "Amount", True),
            ):
                (c.drawRightString if right else c.drawString)(x, y, label)
            y -= LINE_H + 2
        if p_index > 0:
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(X_DESC, y, "Brought forward")
            c.drawRightString(X_AMOUNT, y, _fmt(running))
            y -= LINE_H
        c.setFont("Helvetica", 9)
        for _kind, it, w in lines:
            assert it is not None
            parts = _wrap(it.description)
            if w == 0:
                c.drawString(X_ITEM, y, it.item_no)
                if it.unit:
                    c.drawString(X_UNIT, y, it.unit)
                if it.qty is not None:
                    c.drawRightString(X_QTY + 8, y, f"{it.qty:,.2f}")
                if it.rate is not None:
                    c.drawRightString(X_RATE + 12, y, _fmt(it.rate))
                if it.qty is not None and it.rate is not None:
                    amount = it.qty * it.rate
                    running += amount
                    c.drawRightString(X_AMOUNT, y, _fmt(amount))
            c.setFont("Helvetica-Bold" if it.is_heading else "Helvetica", 9)
            c.drawString(X_DESC, y, parts[w])
            c.setFont("Helvetica", 9)
            y -= LINE_H
        if p_index < len(pages) - 1:
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(X_DESC, y - 4, "Carried forward")
            c.drawRightString(X_AMOUNT, y - 4, _fmt(running))
        c.showPage()
    if collection:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(X_ITEM, TOP, "COLLECTION")
        c.setFont("Helvetica", 9)
        c.drawString(X_DESC, TOP - 30, "Bill No. 1 Earthworks")
        c.drawRightString(X_AMOUNT, TOP - 30, _fmt(running))
        c.drawString(X_DESC, TOP - 44, "Total carried to summary")
        c.drawRightString(X_AMOUNT, TOP - 44, _fmt(running))
        c.showPage()
    c.save()
    return buf.getvalue()


def build_scanned_pdf(items: list[BoqItem], *, embed_answer: bool = True) -> bytes:
    """One image-only page (no text layer) showing the items as a table. With `embed_answer` the rows are also
    printed as an optical code along the top edge (app/demo/bitgrid.py) so the MOCK AI provider can 'read' the
    page like a recorded response; a real provider just sees a few marks."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from app.demo import bitgrid

    img = Image.new("L", (1240, 1754), 255)
    top = 0
    if embed_answer:
        rows = [{"item_no": it.item_no, "description": it.description, "unit": it.unit, "quantity": it.qty} for it in items]
        strip = bitgrid.encode({"rows": rows}, 1240)
        img.paste(strip, (0, 0))
        top = strip.size[1] + 20
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    d.text((80, top + 60), "BILL OF QUANTITIES", fill=0, font=font)
    d.text((80, top + 110), "Item      Description                                   Unit    Qty      Rate", fill=0, font=font)
    y = top + 140
    for it in items:
        d.text((80, y), f"{it.item_no:<9} {it.description[:44]:<44} {(it.unit or ''):<7} {_fmt(it.qty):<9} {_fmt(it.rate)}", fill=0, font=font)
        y += 22
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.drawImage(ImageReader(img), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return buf.getvalue()


def sample_items() -> list[BoqItem]:
    """A small civil bill: two sections, wrapped descriptions, enough rows for 3 pages."""
    items: list[BoqItem] = [BoqItem("1", "EARTHWORKS")]
    items += [
        BoqItem("1.1", "Excavate in all types of soil for roadway including disposal of surplus material off site to approved tip", "m3", 1250.0, 18.5),
        BoqItem("1.2", "Supply and place approved granular sub-base material compacted in layers not exceeding 200mm", "m3", 640.0, 62.0),
        BoqItem("1.3", "Trim and compact formation level to receive sub-base", "m2", 3200.0, 3.5),
    ]
    items.append(BoqItem("2", "DRAINAGE"))
    for i in range(1, 46):
        dia = 150 + (i % 5) * 75
        items.append(
            BoqItem(
                f"2.{i}",
                f"Supply, lay and joint {dia}mm diameter uPVC SN8 pipe in trench including bedding, surround, testing and all "
                f"associated fittings complete as specified, depth {1.0 + (i % 4) * 0.5:.1f}m",
                "m", float(40 + i * 7), 95.0 + dia * 0.4,
            )
        )
    items.append(BoqItem("2.46", "Precast concrete manhole 1200mm internal diameter complete with cover and frame", "nr", 12.0, 4200.0))
    return items
