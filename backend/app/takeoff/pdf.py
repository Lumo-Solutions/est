from __future__ import annotations

import threading
from dataclasses import dataclass
from io import BytesIO

import pdfplumber

from app.takeoff.geometry.entities import GeometricEntity

# PDFium (behind pypdfium2) is not thread-safe: one use at a time, process-wide (shared with the intake's reads).
PDFIUM_LOCK = threading.Lock()
# A page with more drawing objects than this is a CAD export: pdfplumber builds a Python object for each one (a real 8 MB
# A0 sheet with 750,000 took 163 s and 3 GB), so such a page is read with PDFium instead.
HEAVY_PAGE_OBJECTS = 20_000
# Above this many objects a page is not analysed for vector geometry at all (it would need gigabytes): it has no
# geometry entities and is measured through the vision path like a scan.
MAX_GEOMETRY_PAGE_OBJECTS = 150_000

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


def count_page_objects(data: bytes, cap: int) -> list[int]:
    """Drawing objects per page, each counted only up to `cap` + 1 (so the cost stays about that of opening the file)."""
    import pypdfium2 as pdfium

    counts: list[int] = []
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(data)
        try:
            for i in range(len(doc)):
                page = doc[i]
                try:
                    n = 0
                    for _ in page.get_objects():
                        n += 1
                        if n > cap:
                            break
                    counts.append(n)
                finally:
                    page.close()
        finally:
            doc.close()
    return counts


def _pdfium_page_info(data: bytes, index: int) -> PdfPageInfo:
    """`PdfPageInfo` for one page read with PDFium (for the pages pdfplumber cannot afford)."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(data)
        try:
            page = doc[index]
            try:
                w, h = page.get_size()
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range() or ""
                    candidate = textpage.get_text_bounded(left=w * 0.65, bottom=0, right=w, top=h * 0.30) or ""
                finally:
                    textpage.close()
            finally:
                page.close()
        finally:
            doc.close()
    if not candidate:
        candidate = text[-500:] if text else ""
    return PdfPageInfo(
        index=index, width_pt=float(w), height_pt=float(h), raw_text=text, is_raster=len(text.strip()) < _RASTER_CHAR_THRESHOLD,
        title_block_candidate_text=candidate,
    )


def index_pdf(data: bytes) -> list[PdfPageInfo]:
    """Vector PDF page indexing: size, full-page text, and a title-block
    candidate region. Scanned/raster pages are flagged (is_raster=True) for
    the VLM image path in takeoff/titleblock.py rather than OCR'd here
    (deferred -- see docs/architecture.md). A CAD-export page (more than
    HEAVY_PAGE_OBJECTS drawing objects) is read with PDFium, the rest with pdfplumber."""
    pages: list[PdfPageInfo] = []
    heavy = [n > HEAVY_PAGE_OBJECTS for n in count_page_objects(data, HEAVY_PAGE_OBJECTS)]
    with pdfplumber.open(BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i < len(heavy) and heavy[i]:
                pages.append(_pdfium_page_info(data, i))
                continue
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
            page.flush_cache()  # a long drawing set must not keep every page's objects alive
    return pages


_DEFAULT_CAP = "default"


def _default_render_cap() -> int:
    """PDF_RENDER_MAX_PX; the built-in default when no settings are loaded (tools and unit tests)."""
    try:
        from app.core.config import get_settings

        return get_settings().pdf_render_max_px
    except Exception:  # noqa: BLE001 -- settings need a full environment; a render must not
        return 5000


def page_size_pt(data: bytes, page_index: int = 0) -> tuple[float, float]:
    """(width, height) of one page in PDF points, without rendering anything."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(BytesIO(data))
    try:
        page = pdf[page_index]
        try:
            return page.get_size()
        finally:
            page.close()
    finally:
        pdf.close()


def render_page_png(data: bytes, page_index: int, dpi: int = 150, *, max_side_px: int | None | str = _DEFAULT_CAP) -> bytes:
    """Renders one page to PNG for the VLM image path (raster pages, or
    vector pages where text extraction found no usable title-block text).

    The longest side is capped at `max_side_px` (default: the PDF_RENDER_MAX_PX setting; None = no cap) by lowering
    the scale, so an A0 sheet cannot allocate a bitmap of hundreds of megabytes. Pages that fit under the cap render
    exactly as they always did (the AI cache keys on the image bytes). Every pdfium object is closed here."""
    import pypdfium2 as pdfium

    cap = _default_render_cap() if max_side_px == _DEFAULT_CAP else max_side_px
    pdf = pdfium.PdfDocument(BytesIO(data))
    try:
        page = pdf[page_index]
        try:
            scale = dpi / 72
            if cap:
                longest = max(page.get_size()) * scale
                if longest > cap:
                    scale *= cap / longest
            bitmap = page.render(scale=scale)
            try:
                pil_image = bitmap.to_pil()
                try:
                    buf = BytesIO()
                    pil_image.save(buf, format="PNG")
                    return buf.getvalue()
                finally:
                    pil_image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()


def render_title_block_png(data: bytes, page_index: int = 0, dpi: int = 170, max_side_px: int = 1_800) -> bytes:
    """Only the title-block corner (bottom-right ~35% x ~30%, the same region as `crop_title_block_png`), rendered
    straight from the page with pdfium's crop, so a huge sheet never exists as a full-page bitmap."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(BytesIO(data))
    try:
        page = pdf[page_index]
        try:
            w, h = page.get_size()
            region = (w * 0.35, h * 0.30)
            scale = min(dpi / 72, max_side_px / max(region))
            bitmap = page.render(scale=scale, crop=(w * 0.65, 0, 0, h * 0.70))
            try:
                pil_image = bitmap.to_pil()
                try:
                    buf = BytesIO()
                    pil_image.save(buf, format="PNG")
                    return buf.getvalue()
                finally:
                    pil_image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
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


# --------------------------------------------------------------------------
# Module D-B-Phase-4a: vector PDF geometry extraction, feeding the same
# extractor pipeline DXF already uses (app.takeoff.geometry). PDFs have no
# layers, so GeometricEntity.layer is *synthesized* per project from
# stroke colour / line width / dash pattern / (best-effort) optional-
# content-group name, via a small ordered rule set -- see
# docs/module-b-phase4-plan.md §4a.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PdfLayerRule:
    """Mirrors app.models.takeoff.PdfLayerMappingRule (the persisted,
    project-scoped version) -- kept as a plain dataclass here so
    index_pdf_geometry() has no DB/session dependency, same reasoning as
    app.boq.import_parser.BoqImportColumnMapping."""

    target_layer: str
    stroke_color: str | None = None  # hex, e.g. "#ff0000" -- matched case-insensitively
    min_line_width: float | None = None
    max_line_width: float | None = None
    dash_pattern: str | None = None  # "solid" | "dashed" | "dotted"
    ocg_name_contains: str | None = None
    priority: int = 0


_UNMAPPED_LAYER = "UNMAPPED"


def _color_to_hex(color: object) -> str | None:
    """pdfplumber's stroking_color is a raw PDF colour value: a single
    float/int for grayscale (0..1), a 3-tuple for RGB (0..1 each), a
    4-tuple for CMYK, or occasionally a bare int (e.g. 0 for "no colour
    set" -- black) -- normalized to a hex string, or None when it isn't
    recognizably a colour at all."""
    if color is None:
        return None
    if isinstance(color, int | float):
        v = max(0, min(255, round(color * 255)))
        return f"#{v:02x}{v:02x}{v:02x}"
    if isinstance(color, tuple | list):
        if len(color) == 3:
            r, g, b = color
            return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in (r, g, b))
        if len(color) == 4:
            c, m, y, k = color
            r, g, b = 255 * (1 - c) * (1 - k), 255 * (1 - m) * (1 - k), 255 * (1 - y) * (1 - k)
            return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in (r, g, b))
    return None


def _dash_category(dash: object) -> str:
    """dash is pdfplumber's (array, phase) tuple. An empty array is solid;
    a non-empty array whose segments are all short (<=2pt) is treated as
    dotted, anything else dashed -- a deliberately simple categorical
    split (real PDF dash arrays vary a lot; this isn't a dash-pattern
    classifier, just enough to be one of the three signals the brief
    names)."""
    array = dash[0] if isinstance(dash, tuple | list) and dash else []
    if not array:
        return "solid"
    if all(v <= 2 for v in array):
        return "dotted"
    return "dashed"


def _match_pdf_layer(
    rules: list[PdfLayerRule], *, stroke_hex: str | None, line_width: float | None, dash_category: str,
    ocg_name: str | None,
) -> str:
    for rule in sorted(rules, key=lambda r: r.priority):
        if rule.stroke_color and (stroke_hex or "").lower() != rule.stroke_color.lower():
            continue
        if rule.min_line_width is not None and (line_width is None or line_width < rule.min_line_width):
            continue
        if rule.max_line_width is not None and (line_width is None or line_width > rule.max_line_width):
            continue
        if rule.dash_pattern and rule.dash_pattern != dash_category:
            continue
        if rule.ocg_name_contains and rule.ocg_name_contains.lower() not in (ocg_name or "").lower():
            continue
        return rule.target_layer
    return _UNMAPPED_LAYER


def index_pdf_geometry(data: bytes, rules: list[PdfLayerRule] | None = None) -> dict[str, list[GeometricEntity]]:
    """Harvests lines, rects (as closed 4-vertex polylines), and curves
    (as open polylines through their sampled points) per page, keyed
    "page-{1-indexed}" to match index_pdf()'s per-page indexing. A page
    already flagged raster (the same <20-character heuristic index_pdf()
    uses) is skipped entirely -- never guessed at -- and gets an empty
    entity list, same as a DXF layout with nothing extractable.

    OCG (optional content group) membership is genuinely best-effort:
    most CAD-to-PDF exports don't declare OCGs at all, and when they do,
    pdfplumber's per-object dict doesn't surface the owning group name
    directly -- `ocg_name_contains` rules simply never match in that case,
    a real, silent degradation the brief itself anticipates, not a bug.
    """
    rules = rules or []
    result: dict[str, list[GeometricEntity]] = {}
    too_complex = [n > MAX_GEOMETRY_PAGE_OBJECTS for n in count_page_objects(data, MAX_GEOMETRY_PAGE_OBJECTS)]

    with pdfplumber.open(BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            page_label = f"page-{i + 1}"
            if i < len(too_complex) and too_complex[i]:
                result[page_label] = []  # too many objects to analyse here: left to the vision path
                continue
            text = page.extract_text() or ""
            if len(text.strip()) < _RASTER_CHAR_THRESHOLD:
                result[page_label] = []
                continue

            geoms: list[GeometricEntity] = []
            for idx, ln in enumerate(page.lines):
                layer = _match_pdf_layer(
                    rules, stroke_hex=_color_to_hex(ln.get("stroking_color")), line_width=ln.get("linewidth"),
                    dash_category=_dash_category(ln.get("dash")), ocg_name=None,
                )
                geoms.append(
                    GeometricEntity("line", layer, f"line-{idx}", [(ln["x0"], ln["y0"]), (ln["x1"], ln["y1"])])
                )
            for idx, rc in enumerate(page.rects):
                layer = _match_pdf_layer(
                    rules, stroke_hex=_color_to_hex(rc.get("stroking_color")), line_width=rc.get("linewidth"),
                    dash_category=_dash_category(rc.get("dash")), ocg_name=None,
                )
                x0, y0, x1, y1 = rc["x0"], rc["y0"], rc["x1"], rc["y1"]
                geoms.append(
                    GeometricEntity(
                        "lwpolyline", layer, f"rect-{idx}", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True,
                    )
                )
            for idx, cv in enumerate(page.curves):
                layer = _match_pdf_layer(
                    rules, stroke_hex=_color_to_hex(cv.get("stroking_color")), line_width=cv.get("linewidth"),
                    dash_category=_dash_category(cv.get("dash")), ocg_name=None,
                )
                # curve "pts" are in pdfplumber's top-down display
                # coordinates (confirmed empirically against the same
                # object type's own x0/y0/x1/y1, which are PDF-native
                # bottom-up) -- flipped here so every entity this function
                # returns shares one consistent, PDF-native coordinate
                # system, matching lines/rects above.
                pts = cv.get("pts") or []
                verts = [(x, page.height - y) for x, y in pts]
                if len(verts) >= 2:
                    geoms.append(GeometricEntity("lwpolyline", layer, f"curve-{idx}", verts))
            result[page_label] = geoms
            page.flush_cache()

    return result
