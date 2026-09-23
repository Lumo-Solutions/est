from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pdfplumber

# A page with fewer than this many extracted characters and no title-block
# candidate text is treated as raster (scanned) rather than vector.
_RASTER_CHAR_THRESHOLD = 20


@dataclass(slots=True)
class PdfPageInfo:
    index: int
    width_pt: float
    height_pt: float
    raw_text: str
    is_raster: bool
    title_block_candidate_text: str


def _title_block_region_text(page: "pdfplumber.page.Page") -> str:
    """Words within the bottom-right ~35% x ~30% of the sheet -- the
    conventional title-block location on most engineering drawing sheets."""
    width, height = page.width, page.height
    x0 = width * 0.65
    y0 = height * 0.70
    cropped = page.within_bbox((x0, y0, width, height))
    return cropped.extract_text() or ""


def index_pdf(data: bytes) -> list[PdfPageInfo]:
    """Vector PDF page indexing: size, full-page text, and a title-block
    candidate region. Scanned/raster pages are flagged (is_raster=True) for
    the VLM image path in takeoff/titleblock.py rather than OCR'd here
    (deferred -- see docs/architecture.md)."""
    pages: list[PdfPageInfo] = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            candidate = _title_block_region_text(page)
            if not candidate:
                candidate = text[-500:] if text else ""
            is_raster = len(text.strip()) < _RASTER_CHAR_THRESHOLD
            pages.append(
                PdfPageInfo(
                    index=i,
                    width_pt=float(page.width),
                    height_pt=float(page.height),
                    raw_text=text,
                    is_raster=is_raster,
                    title_block_candidate_text=candidate,
                )
            )
    return pages


def render_page_png(data: bytes, page_index: int, dpi: int = 150) -> bytes:
    """Renders one page to PNG for the VLM image path (raster pages, or
    vector pages where text extraction found no usable title-block text)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(BytesIO(data))
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=dpi / 72)
        pil_image = bitmap.to_pil()
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


def crop_title_block_png(png_bytes: bytes) -> bytes:
    """Crops the bottom-right title-block region out of a rendered page PNG,
    matching the same region used by _title_block_region_text()."""
    from PIL import Image

    img = Image.open(BytesIO(png_bytes))
    w, h = img.size
    box = (int(w * 0.65), int(h * 0.70), w, h)
    cropped = img.crop(box)
    buf = BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()
