"""PDF BOQ extraction orchestrator: deterministic table parse first, the vision
task only for pages the parser flagged (docs/ai-plan.md §4-5).

An AI-read row is always flagged ``source='ai'`` with its page and region, has
its confidence capped, never carries a rate or amount (the schema has none),
and goes through the same review wizard as any other row. If the AI is not
available (not configured / not allowed / over budget / provider down) the page
is reported as ``ai_unavailable`` so the estimator knows it was NOT read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.ai.errors import AIError, describe_reason
from app.ai.gateway import AIGateway, AIMeta
from app.ai.provider import VISION, ImageInput
from app.boq.pdf_reader import PageResult, PdfBoqRow, read_pdf_boq
from app.core.config import Settings
from app.takeoff.pdf import render_page_png
from app.takeoff.prompts import load_schema, render_prompt

AI_CONFIDENCE_CAP = 0.80
PAGE_TEXT_CHARS = 6_000
PROMPT_VERSION = "1"

ProgressFn = Callable[[int, int, str], Awaitable[None]]


@dataclass(slots=True)
class PdfExtraction:
    pages: list[PageResult]
    warnings: list[str] = field(default_factory=list)

    @property
    def rows(self) -> list[PdfBoqRow]:
        return [r for p in self.pages for r in p.rows]

    def counts(self) -> dict[str, int]:
        out = {"total": len(self.pages), "table": 0, "ai": 0, "skipped": 0, "empty": 0, "unread": 0}
        for p in self.pages:
            if p.status == "table":
                out["table"] += 1
            elif p.status == "ai":
                out["ai"] += 1
            elif p.status == "skipped_collection":
                out["skipped"] += 1
            elif p.status == "empty":
                out["empty"] += 1
            else:
                out["unread"] += 1
        return out


def _page_text(data: bytes, index: int) -> str:
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return (pdf.pages[index].extract_text() or "")[:PAGE_TEXT_CHARS]


def _rows_from_ai(raw: dict, page: int, size: list[float]) -> list[PdfBoqRow]:
    confidence = min(float(raw.get("confidence") or 0.6), AI_CONFIDENCE_CAP)
    rows: list[PdfBoqRow] = []
    for r in raw.get("rows", []):
        bbox = r.get("bbox")
        if bbox and len(bbox) == 4 and all(0.0 <= v <= 1.0 for v in bbox):
            points = [bbox[0] * size[0], bbox[1] * size[1], bbox[2] * size[0], bbox[3] * size[1]]
        else:
            points = [0.0, 0.0, 0.0, 0.0]
        qty = r.get("quantity")
        rows.append(
            PdfBoqRow(
                page=page, item_no=(r.get("item_no") or None), description=(r.get("description") or "").strip(),
                uom=(r.get("unit") or None), quantity=float(qty) if qty is not None else None,
                quantity_raw=None if qty is None else f"{qty:g}", rate_raw=None, amount_raw=None,
                bbox=points, page_size=size, source="ai", confidence=confidence,
            )
        )
    return [r for r in rows if r.description]


def default_gateway(settings: Settings | None = None) -> AIGateway:
    from app.ai.factory import default_gateway as _factory

    return _factory(settings)


async def extract_pdf_boq(
    data: bytes,
    *,
    meta: AIMeta | None = None,
    gateway: AIGateway | None = None,
    use_ai: bool = True,
    on_progress: ProgressFn | None = None,
) -> PdfExtraction:
    pages = read_pdf_boq(data)
    warnings: list[str] = []
    total = len(pages)
    gw = gateway
    for done, page in enumerate(pages, start=1):
        if page.status == "needs_ai":
            if not use_ai:
                page.note = f"{page.note}; AI reading disabled".strip("; ")
            else:
                gw = gw or default_gateway()
                await _read_page_with_ai(gw, data, page, meta, warnings)
        if on_progress is not None:
            await on_progress(done, total, page.status)
    unread = [p.page for p in pages if p.status in ("needs_ai", "ai_unavailable")]
    if unread:
        warnings.append(
            "These pages could not be read and have no rows: "
            + ", ".join(str(n) for n in unread[:30])
            + ("..." if len(unread) > 30 else "")
            + ". Add those items by hand or fix the source PDF."
        )
    return PdfExtraction(pages, warnings)


async def _read_page_with_ai(
    gw: AIGateway, data: bytes, page: PageResult, meta: AIMeta | None, warnings: list[str]
) -> None:
    idx = page.page - 1
    try:
        png = render_page_png(data, idx)
        text = _page_text(data, idx)
        system, user = render_prompt("boq_pdf_rows.j2", page_number=page.page, page_text=text, has_image=True)
        page_meta = AIMeta(
            project_id=meta.project_id if meta else None,
            entity_type=(meta.entity_type if meta else None) or "boq_pdf_page",
            entity_id=f"{meta.entity_id if meta and meta.entity_id else ''}#p{page.page}",
        )
        result = await gw.run(
            task="boq_pdf_rows", kind=VISION, system=system, user=user,
            schema=load_schema("boq_pdf_rows.schema.json"), images=[ImageInput(png, "image/png")],
            max_tokens=4096, prompt_version=PROMPT_VERSION, meta=page_meta,
        )
    except AIError as exc:
        page.status = "ai_unavailable"
        page.note = f"AI unavailable: {describe_reason(exc.code)}"
        return
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        p = pdf.pages[idx]
        size = [float(p.width), float(p.height)]
    if not result.data.get("is_boq_table"):
        page.status, page.note = "empty", "AI: no BOQ item rows on this page"
        return
    page.rows = _rows_from_ai(result.data, page.page, size)
    page.status = "ai"
    page.note = "AI-read: review before importing"
    page.quality = min(float(result.data.get("confidence") or 0.6), AI_CONFIDENCE_CAP)
