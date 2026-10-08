"""AI-first classification of a tender document.

Every file goes to the AI provider with its filename, folder path, file type,
the text of its first pages (or a spreadsheet's sheet names and first rows) and,
only when the text is not enough, page images for the vision model. The
deterministic rules (intake/rules.py) still run, but they are *hints* in the
prompt and the fallback when the AI is off, not configured, over budget or
failing: that result is labelled "classified by rules".

The model can only pick values from the schema (enum class, discipline, drawing
type, a few printed fields). Nothing here reads anything else from its answer,
Pydantic drops unknown keys, and a model failure never fails the document.
Every result is a *proposal*; the tenant's auto-accept threshold or a person
decides whether it is routed (services/tender_intake_processing.py).
"""

from __future__ import annotations

import base64
import io
import logging
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.ai.compat import extract_json
from app.ai.gateway import AIMeta
from app.core.config import Settings
from app.intake.constants import (
    ALL_CLASSES,
    DRAWING_SUB_TYPES,
    DRAWING_TYPES,
    ClassificationSource,
    DocClass,
    Flag,
)
from app.intake.extract import PDFIUM_LOCK as _PDFIUM_LOCK
from app.intake.extract import DocContent
from app.intake.rules import DENSE_VECTOR_PRIMITIVES, RuleOutcome
from app.takeoff.prompts import load_schema, render_prompt

logger = logging.getLogger(__name__)

PROMPT_VERSION = "2"
MODEL_CONFIDENCE_CAP = 0.99
MODEL_TEXT_PAGES = 2
MODEL_TEXT_CHARS = 6_000
MODEL_MAX_TOKENS = 700
# Below this much readable text a PDF is sent as an image too; at or above it the text model is enough.
TEXT_SUFFICIENT_CHARS = 150
TITLE_BLOCK_SUFFICIENT_CHARS = 40
MIN_READABLE_CHARS = 20
IMAGE_MAX_SIDE_PX = 1_800
# A page whose 170 dpi bitmap would be bigger than this (about A1 and up) has only its title-block corner rendered.
TITLE_BLOCK_FULL_RENDER_MAX_PIXELS = 30_000_000
# PDFium (behind pypdfium2) is not thread-safe: one use at a time, process-wide (the lock lives in intake/extract.py,
# which parses PDFs too).

# Text in a document that tries to steer the classifier. It is never obeyed (the prompt fences the content and the
# schema has no action fields); seeing it only withholds auto-accept so a person looks at the file.
_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|the\s+)*(?:previous|prior|above|earlier)\b"
    r"|disregard\s+(?:all\s+|the\s+)*(?:previous|above|instructions)"
    r"|\b(?:classify|mark|label|file|treat|set)\s+(?:this|it|the\s+document)\s+as\b"
    r"|\bauto[-\s]?accept\b|\bapprove\s+(?:this|it|immediately)\b"
    r"|\bset\s+(?:the\s+)?confidence\b|\bconfidence\s*(?:=|:|of|to)\s*(?:1(?:\.0+)?|100\s*%)"
    r"|\b(?:you\s+are\s+now|new\s+instructions|system\s+prompt)\b",
    re.I,
)


def looks_like_injection(*texts: str | None) -> str | None:
    """The matched phrase when any text contains instruction-like content aimed at the classifier, else None."""
    for text in texts:
        if text and (m := _INJECTION.search(text)):
            return m.group(0)[:80]
    return None


class ModelMetadata(BaseModel):
    document_number: str | None = None
    title: str | None = None
    revision: str | None = None
    date: str | None = None
    discipline: str | None = None
    sheet_number: str | None = None
    scale: str | None = None
    unit_type: str | None = None
    addendum_number: str | None = None
    addendum_issue_date: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    amends: list[str] = Field(default_factory=list)
    sheet_names: list[str] = Field(default_factory=list)
    header_row: int | None = None


class ModelClassification(BaseModel):
    doc_class: str
    sub_type: str | None = None
    drawing_type: str | None = None
    confidence: float = 0.0
    evidence_quote: str | None = None
    evidence_page: int | None = None
    metadata: ModelMetadata = Field(default_factory=ModelMetadata)


@dataclass(slots=True)
class Proposal:
    doc_class: str
    sub_type: str | None
    confidence: float
    source: str
    evidence: list[dict]
    metadata: dict
    flags: list[str] = field(default_factory=list)


def parse_model_output(raw: dict) -> ModelClassification:
    """Validate a raw model answer. Raises ValueError for anything outside the schema's enums."""
    parsed = ModelClassification.model_validate(raw)
    if parsed.doc_class not in ALL_CLASSES:
        raise ValueError(f"unknown doc_class {parsed.doc_class!r}")
    if parsed.sub_type is not None and parsed.sub_type not in DRAWING_SUB_TYPES:
        parsed.sub_type = None
    if parsed.drawing_type is not None and parsed.drawing_type not in DRAWING_TYPES:
        parsed.drawing_type = None
    if parsed.doc_class != DocClass.DRAWING.value:
        parsed.sub_type = None
        parsed.drawing_type = None
    parsed.confidence = min(max(parsed.confidence, 0.0), 1.0)
    return parsed


# ------------------------------------------------------------------ what the AI is shown
def ai_document_text(content: DocContent) -> str:
    """The first one or two pages (PDF, DOCX, DXF text), or sheet names with their first rows (spreadsheets)."""
    if content.sheets and content.ext in ("xlsx", "csv", "xls"):
        parts = []
        for sheet in content.sheets[:6]:
            head = f"[Sheet: {sheet.name}]"
            if sheet.header_row:
                head += f" column headings on row {sheet.header_row}: {' | '.join(sheet.columns[:12])}"
            parts.append(f"{head}\n{sheet.sample_text}")
        return "\n\n".join(parts)[:MODEL_TEXT_CHARS]
    if content.page_texts:
        return "\n\n".join(f"[Page {i + 1}]\n{t}" for i, t in enumerate(content.page_texts[:MODEL_TEXT_PAGES]) if t.strip())[:MODEL_TEXT_CHARS]
    return (content.text or "")[:MODEL_TEXT_CHARS]


def text_is_sufficient(content: DocContent) -> bool:
    """False when the text model cannot do the job alone (scans, sheets that are all linework, images)."""
    if content.ext in ("jpg", "jpeg", "png") or content.needs_image:
        return False
    if content.ext != "pdf":
        return True  # xlsx/csv/docx/dxf: what there is to read is text; dwg/xls have no parser and no image
    text_len = len((content.text or "").strip())
    if text_len >= TEXT_SUFFICIENT_CHARS:
        return True
    if len((content.title_block_text or "").strip()) >= TITLE_BLOCK_SUFFICIENT_CHARS:
        return True
    if text_len < MIN_READABLE_CHARS:
        return False  # next to nothing to read: a blank sheet, a stamp, a scan with a few stray characters
    # A short text-only page (a cover note, a letter, an RFI) says what it is. A short text on a sheet full of
    # linework is a drawing whose words are all in an image-like title block: look at it.
    return content.vector_density < DENSE_VECTOR_PRIMITIVES // 2


def rule_hints(rules: RuleOutcome, limit: int = 3) -> list[dict]:
    """What the deterministic rules suspect, for the prompt. Never the answer, only a hint."""
    by_class: dict[str, list[str]] = {}
    for ev in rules.evidence:
        if ev.get("class") and ev.get("rule") not in ("model", "no_rule_fired", "no_text_layer"):
            by_class.setdefault(ev["class"], []).append(str(ev["rule"]))
    ranked = sorted(rules.candidates.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [
        {"doc_class": cls, "why": ", ".join(by_class.get(cls, [])[:3]) or "weak signal"}
        for cls, conf in ranked
        if conf >= 0.3 and cls in by_class
    ]


def _shrink(png: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        if max(img.size) <= IMAGE_MAX_SIDE_PX:
            return png
        img = img.convert("RGB")
        img.thumbnail((IMAGE_MAX_SIDE_PX, IMAGE_MAX_SIDE_PX))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()


def build_images(ext: str, data: bytes, content: DocContent) -> list[bytes]:
    """Page 1 (and, for a sheet that looks like a drawing, its title-block area at higher resolution). Empty when
    the file has no renderable page."""
    try:
        if ext == "pdf":
            from app.takeoff.pdf import crop_title_block_png, page_size_pt, render_page_png, render_title_block_png

            with _PDFIUM_LOCK:
                images = [_shrink(render_page_png(data, 0, dpi=100, max_side_px=None))]
                if content.vector_density >= DENSE_VECTOR_PRIMITIVES // 2 or content.title_block_text:
                    w, h = page_size_pt(data, 0)
                    if (w * 170 / 72) * (h * 170 / 72) <= TITLE_BLOCK_FULL_RENDER_MAX_PIXELS:
                        # Same bytes as ever for ordinary sheets (the AI cache keys on them).
                        images.append(crop_title_block_png(render_page_png(data, 0, dpi=170, max_side_px=None)))
                    else:
                        # A0 and bigger: render only the corner, never the whole sheet at 170 dpi (hundreds of MB).
                        images.append(render_title_block_png(data, 0, dpi=170, max_side_px=IMAGE_MAX_SIDE_PX))
            return images
        if ext in ("jpg", "jpeg", "png"):
            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                out = io.BytesIO()
                img.convert("RGB").save(out, format="PNG")
                return [_shrink(out.getvalue())]
    except Exception:  # noqa: BLE001 -- no image just means the model works from the filename and text
        logger.warning("tender_intake: could not render a page image", exc_info=True)
    return []


async def classify_with_model(
    *, filename: str, content: DocContent, candidates: list[str] | None = None, image_png: bytes | None = None,
    images: list[bytes] | None = None, folder_path: str | None = None, hints: list[dict] | None = None,
    meta: AIMeta | None = None,
) -> ModelClassification:
    """One AI call for one document. Raises whatever the gateway raises (AIError subclasses); the caller falls
    back to the rules."""
    pics = list(images or ([image_png] if image_png else []))
    if hints is None and candidates:
        hints = [{"doc_class": c, "why": "rules were undecided"} for c in candidates]
    system_prompt, user_prompt = render_prompt(
        "document_classification.j2",
        filename=filename,
        folder_path=folder_path or "",
        file_type=content.ext or "",
        page_count=content.pages,
        document_text=ai_document_text(content),
        title_block_text=(content.title_block_text or "")[:2_000] if content.ext != "dxf" else "",
        has_image=bool(pics),
        hints=hints or [],
    )
    urls = [f"data:image/png;base64,{base64.b64encode(p).decode('ascii')}" for p in pics]
    raw = await extract_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_schema=load_schema("document_classification.schema.json"),
        image_data_urls=urls or None,
        max_tokens=MODEL_MAX_TOKENS,
        task="intake_classify",
        meta=meta,
        prompt_version=PROMPT_VERSION,
    )
    return parse_model_output(raw)


# ------------------------------------------------------------------ combining
# Printed identifiers: the rules read them verbatim from the title block, so they win when they found one.
_RULES_FIRST_KEYS = ("document_number", "revision", "scale", "sheet_number", "date", "boq_sheet", "boq_columns", "header_row", "sheet_names")
_STRONG_RULES = 0.85


def _model_metadata_dict(model: ModelClassification) -> dict:
    dumped = model.metadata.model_dump()
    md = {k: v for k, v in dumped.items() if v not in (None, "", [])}
    if model.drawing_type:
        md["drawing_type"] = model.drawing_type
    return md


def rules_proposal(rules: RuleOutcome, *, reason: str | None, settings: Settings) -> Proposal:
    """The fallback: the rules decide, and the result says so ("classified by rules")."""
    flags = [Flag.RULES_FALLBACK.value]
    if rules.conflict:
        flags.append(Flag.CONFLICT.value)
    metadata = dict(rules.metadata)
    if reason:
        metadata["ai_unavailable_reason"] = reason
    proposal = Proposal(rules.doc_class, rules.sub_type, rules.confidence, ClassificationSource.RULES.value, list(rules.evidence), metadata, flags)
    if proposal.confidence < settings.intake_bulk_confirm_min:
        proposal.flags.append(Flag.LOW_CONFIDENCE.value)
    return proposal


def combine(rules: RuleOutcome, model: ModelClassification | None, *, settings: Settings, reason: str | None = None) -> Proposal:
    """The AI's answer is the proposal; the rules' findings ride along as evidence and fill identifiers the AI left out."""
    if model is None:
        return rules_proposal(rules, reason=reason, settings=settings)

    flags: list[str] = []
    confidence = round(min(model.confidence, MODEL_CONFIDENCE_CAP), 3)
    quote = {"rule": "model", "class": model.doc_class, "weight": confidence, "matched": model.evidence_quote or "", "page": model.evidence_page}
    evidence = [quote, *rules.evidence]

    metadata = dict(rules.metadata)
    for key, value in _model_metadata_dict(model).items():
        if key in _RULES_FIRST_KEYS and metadata.get(key):
            continue
        metadata[key] = value

    sub_type = model.sub_type
    if model.doc_class == DocClass.DRAWING.value and sub_type is None and rules.doc_class == DocClass.DRAWING.value:
        sub_type = rules.sub_type

    # Strong, deterministic evidence for another class than the AI's: a person should look.
    if model.doc_class != rules.doc_class and rules.confidence >= _STRONG_RULES:
        flags.append(Flag.CONFLICT.value)
    if confidence < settings.intake_bulk_confirm_min:
        flags.append(Flag.LOW_CONFIDENCE.value)
    return Proposal(model.doc_class, sub_type, confidence, ClassificationSource.MODEL.value, evidence, metadata, flags)
