"""Stage 2: the local model, only for documents stage 1 could not settle.

The model can only pick values from the schema (enum class, sub type, a few
printed fields). Nothing here reads anything else from its answer, Pydantic
drops unknown keys, and a model failure never fails the document: stage 1's
proposal stands, flagged. Every result is a *proposal*.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.ai.compat import extract_json
from app.ai.gateway import AIMeta
from app.intake.constants import ALL_CLASSES, DRAWING_SUB_TYPES, ClassificationSource, Flag
from app.intake.extract import DocContent
from app.intake.rules import RuleOutcome
from app.takeoff.prompts import load_schema, render_prompt

MODEL_CONFIDENCE_CAP = 0.90
MODEL_TEXT_CHARS = 6_000
MODEL_MAX_TOKENS = 700


class ModelMetadata(BaseModel):
    document_number: str | None = None
    title: str | None = None
    revision: str | None = None
    date: str | None = None
    discipline: str | None = None
    sheet_number: str | None = None
    scale: str | None = None
    addendum_number: str | None = None
    addendum_issue_date: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    sheet_names: list[str] = Field(default_factory=list)
    header_row: int | None = None


class ModelClassification(BaseModel):
    doc_class: str
    sub_type: str | None = None
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
    if parsed.doc_class != "drawing":
        parsed.sub_type = None
    parsed.confidence = min(max(parsed.confidence, 0.0), 1.0)
    return parsed


async def classify_with_model(
    *, filename: str, content: DocContent, candidates: list[str], image_png: bytes | None = None,
    folder_path: str | None = None, meta: AIMeta | None = None,
) -> ModelClassification:
    system_prompt, user_prompt = render_prompt(
        "document_classification.j2",
        filename=filename,
        folder_path=folder_path or "",
        document_text=(content.text or "")[:MODEL_TEXT_CHARS],
        title_block_text=(content.title_block_text or "")[:2_000],
        has_image=image_png is not None,
        candidates=candidates,
    )
    image_data_url = f"data:image/png;base64,{base64.b64encode(image_png).decode('ascii')}" if image_png else None
    raw = await extract_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_schema=load_schema("document_classification.schema.json"),
        image_data_url=image_data_url,
        max_tokens=MODEL_MAX_TOKENS,
        task="intake_classify",
        meta=meta,
    )
    return parse_model_output(raw)


def _model_metadata_dict(model: ModelClassification) -> dict:
    dumped = model.metadata.model_dump()
    md = {k: v for k, v in dumped.items() if v not in (None, "", [])}
    if "supersedes" in md and "amends" not in md:
        md["supersedes"] = list(md["supersedes"])
    return md


def combine(rules: RuleOutcome, model: ModelClassification | None, *, model_wanted: bool, settings: Settings) -> Proposal:
    """Merge stage 1 and stage 2 into the single proposal shown to the reviewer."""
    flags: list[str] = []
    evidence = list(rules.evidence)
    metadata = dict(rules.metadata)

    if model is None:
        if model_wanted:
            flags.append(Flag.MODEL_UNAVAILABLE.value)
        if rules.conflict:
            flags.append(Flag.CONFLICT.value)
        proposal = Proposal(rules.doc_class, rules.sub_type, rules.confidence, ClassificationSource.RULES.value, evidence, metadata, flags)
    else:
        model_conf = min(model.confidence, MODEL_CONFIDENCE_CAP)
        quote = {"rule": "model", "class": model.doc_class, "weight": round(model_conf, 3), "matched": model.evidence_quote or "", "page": model.evidence_page}
        evidence.insert(0, quote)
        for key, value in _model_metadata_dict(model).items():
            metadata.setdefault(key, value)
        if model.doc_class in rules.candidates:
            confidence = round((model_conf + rules.candidates[model.doc_class]) / 2, 3)
            if rules.conflict and model.doc_class != rules.doc_class:
                flags.append(Flag.CONFLICT.value)
            sub = model.sub_type or (rules.sub_type if model.doc_class == rules.doc_class else None)
            proposal = Proposal(model.doc_class, sub, confidence, ClassificationSource.MODEL.value, evidence, metadata, flags)
        elif model_conf >= 0.5:
            proposal = Proposal(model.doc_class, model.sub_type, round(model_conf * 0.9, 3), ClassificationSource.MODEL.value, evidence, metadata, flags)
        else:
            flags.append(Flag.LOW_CONFIDENCE.value)
            proposal = Proposal(rules.doc_class, rules.sub_type, rules.confidence, ClassificationSource.RULES.value, evidence, metadata, flags)

    if proposal.confidence < settings.intake_bulk_confirm_min and Flag.LOW_CONFIDENCE.value not in proposal.flags:
        proposal.flags.append(Flag.LOW_CONFIDENCE.value)
    return proposal
