"""Stage 1 classification: deterministic rules, no model, no GPU.

Every rule that fires produces a ``Hit`` (class, weight, the rule name and
the matched text, plus page). Hits for the same class combine noisy-or
(``1 - prod(1 - w)``, capped at 0.98). A keyword found deep in the body counts
half as much as one in the first three lines, so an addendum that merely
*mentions* the Bill of Quantities is not mistaken for a BOQ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.intake.constants import DocClass
from app.intake.extract import DocContent
from app.intake.metadata import DOC_NO, discipline_to_sub_type, extract_metadata

CONFIDENCE_CAP = 0.98
CONFLICT_RUNNER_UP = 0.5
_TITLE_LINES = 3
DENSE_VECTOR_PRIMITIVES = 400


@dataclass(frozen=True, slots=True)
class Hit:
    doc_class: str
    weight: float
    rule: str
    matched: str
    page: int | None = None


@dataclass(slots=True)
class RuleOutcome:
    doc_class: str
    sub_type: str | None
    confidence: float
    evidence: list[dict]
    metadata: dict
    conflict: bool
    candidates: dict[str, float]


_TEXT_RULES: tuple[tuple[str, float, str, re.Pattern[str]], ...] = (
    (DocClass.ADDENDUM.value, 0.90, "addendum_title", re.compile(r"ADDENDUM\s*(?:NO\.?|NUMBER|#)?\s*\d+", re.I)),
    (DocClass.BOQ.value, 0.80, "boq_title", re.compile(r"BILLS?\s+OF\s+QUANTIT\w+|SCHEDULES?\s+OF\s+QUANTIT\w+", re.I)),
    (DocClass.CONTRACT.value, 0.85, "contract_terms", re.compile(r"CONDITIONS\s+OF\s+CONTRACT|PARTICULAR\s+CONDITIONS|GENERAL\s+CONDITIONS|\bFIDIC\b", re.I)),
    (DocClass.TENDER_INSTRUCTIONS.value, 0.85, "instructions_to_tenderers", re.compile(r"INSTRUCTIONS?\s+TO\s+(?:TENDERERS|BIDDERS)", re.I)),
    (DocClass.TENDER_FORMS.value, 0.85, "tender_forms", re.compile(r"FORM\s+OF\s+TENDER|BID\s+BOND|BID\s+SECURITY|PERFORMANCE\s+(?:BOND|GUARANTEE)|APPENDIX\s+TO\s+TENDER", re.I)),
    (DocClass.CLARIFICATION.value, 0.80, "clarification", re.compile(r"REQUEST\s+FOR\s+INFORMATION|\bRFI\s*(?:NO\.?|#)?\s*\d+|CLARIFICATION\s*(?:NO\.?|#)\s*\d+|RESPONSE\s+TO\s+(?:QUERY|QUERIES|RFI)", re.I)),
    (DocClass.PROGRAMME.value, 0.70, "programme", re.compile(r"\bPROGRAMME\b|\bGANTT\b|BASELINE\s+(?:PROGRAMME|SCHEDULE)", re.I)),
    (DocClass.SITE_INVESTIGATION.value, 0.85, "geotechnical", re.compile(r"GEOTECHNICAL|SOIL\s+INVESTIGATION|SITE\s+INVESTIGATION|GROUND\s+INVESTIGATION|\bBOREHOLE\b", re.I)),
    (DocClass.SPECIFICATION.value, 0.80, "spec_section", re.compile(r"\bSECTION\s+\d{2}\s?\d{2}\s?\d{2}\b", re.I)),
    (DocClass.SPECIFICATION.value, 0.70, "spec_part_general", re.compile(r"\bPART\s+1\s*[-:]?\s*GENERAL\b", re.I)),
    (DocClass.SPECIFICATION.value, 0.50, "spec_word", re.compile(r"\bSPECIFICATIONS?\b", re.I)),
    (DocClass.CORRESPONDENCE.value, 0.70, "letter_phrases", re.compile(r"\bDEAR\s+(?:SIRS?|MADAM|MR|MS)\b|\bYOURS\s+(?:FAITHFULLY|SINCERELY)\b|\bFURTHER\s+TO\s+(?:OUR|YOUR)\b", re.I)),
)

_FILENAME_RULES: tuple[tuple[str, float, str, re.Pattern[str]], ...] = (
    (DocClass.ADDENDUM.value, 0.70, "filename_addendum", re.compile(r"(?<![A-Za-z0-9])ADD(?:ENDUM)?[-_ ]?\d+|(?<![A-Za-z0-9])ADDENDUM(?![A-Za-z0-9])", re.I)),
    (DocClass.BOQ.value, 0.60, "filename_boq", re.compile(r"(?<![A-Za-z0-9])BOQ(?![A-Za-z0-9])|BILL[-_ ]?OF[-_ ]?QUANT", re.I)),
    (DocClass.DRAWING.value, 0.60, "filename_drawing", re.compile(r"(?<![A-Za-z0-9])DWG(?![A-Za-z0-9])|(?<![A-Za-z0-9])[A-Z]{1,3}-\d{2,4}(?![A-Za-z0-9]).*(?<![A-Za-z0-9])REV(?![A-Za-z0-9])", re.I)),
    (DocClass.SPECIFICATION.value, 0.55, "filename_spec", re.compile(r"(?<![A-Za-z0-9])SPEC", re.I)),
    (DocClass.CONTRACT.value, 0.55, "filename_contract", re.compile(r"CONTRACT|CONDITIONS", re.I)),
    (DocClass.TENDER_INSTRUCTIONS.value, 0.55, "filename_itt", re.compile(r"(?<![A-Za-z0-9])ITT(?![A-Za-z0-9])|INSTRUCTIONS", re.I)),
    (DocClass.TENDER_FORMS.value, 0.55, "filename_forms", re.compile(r"FORM[-_ ]OF[-_ ]TENDER|(?<![A-Za-z0-9])BOND(?![A-Za-z0-9])|TENDER[-_ ]FORM", re.I)),
    (DocClass.CLARIFICATION.value, 0.55, "filename_rfi", re.compile(r"(?<![A-Za-z0-9])RFI(?![A-Za-z0-9])|CLARIFICATION", re.I)),
    (DocClass.PROGRAMME.value, 0.55, "filename_programme", re.compile(r"(?<![A-Za-z0-9])PROG(?:RAMME)?(?![A-Za-z0-9])|GANTT", re.I)),
    (DocClass.SITE_INVESTIGATION.value, 0.55, "filename_geotech", re.compile(r"GEOTECH|SOIL|BOREHOLE", re.I)),
    (DocClass.CORRESPONDENCE.value, 0.55, "filename_letter", re.compile(r"LETTER|CORRESPONDENCE|EMAIL", re.I)),
)


def _basename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _title_zone_end(text: str) -> int:
    """Offset just past the first few non-empty lines: where a document states what it is."""
    seen = 0
    for m in re.finditer(r"[^\n]+", text):
        if m.group(0).strip():
            seen += 1
            if seen == _TITLE_LINES:
                return m.end()
    return len(text)


def _text_hits(content: DocContent) -> list[Hit]:
    hits: list[Hit] = []
    for page_idx, page_text in enumerate(content.page_texts or ([content.text] if content.text else [])):
        for cls, weight, rule, pattern in _TEXT_RULES:
            m = pattern.search(page_text)
            if not m:
                continue
            # Only page 1's position matters for the title-zone bonus; later pages count as body text.
            in_title = page_idx == 0 and m.start() < _title_zone_end(page_text)
            hits.append(Hit(cls, weight if in_title else weight * 0.5, rule, m.group(0)[:80], page_idx + 1))
    return hits


def _structure_hits(content: DocContent) -> list[Hit]:
    hits: list[Hit] = []
    if content.ext == "dxf":
        hits.append(Hit(DocClass.DRAWING.value, 0.95, "ext_dxf", ".dxf"))
    elif content.ext == "dwg":
        hits.append(Hit(DocClass.DRAWING.value, 0.90, "ext_dwg", ".dwg"))

    best = content.best_sheet
    if best is not None:
        weight = 0.95 if best.header_score >= 5 else 0.90
        hits.append(Hit(DocClass.BOQ.value, weight, "xlsx_header", f"{best.name}!row {best.header_row}: {', '.join(best.columns[:6])}"))
    for sheet in content.sheets:
        low = sheet.sample_text.lower()
        if "activity" in low and ("finish" in low or "start" in low) and best is None:
            hits.append(Hit(DocClass.PROGRAMME.value, 0.80, "xlsx_programme_header", f"{sheet.name}: activity/start/finish"))
            break

    block = content.title_block_text or ""
    has_no = bool(re.search(r"(?:DRAWING|DWG)\s*(?:NO|NUMBER|#)", block, re.I) or DOC_NO.search(block))
    has_rev_or_scale = bool(re.search(r"\bREV(?:ISION)?\b|\bSCALE\b", block, re.I))
    if content.ext in ("pdf", "dxf") and has_no and has_rev_or_scale:
        m = re.search(r"(?:DRAWING|DWG)\s*(?:NO\.?|NUMBER|#)\s*[:.\-]?\s*\S+|" + DOC_NO.pattern, block, re.I)
        hits.append(Hit(DocClass.DRAWING.value, 0.90, "title_block", (m.group(0) if m else "title block")[:80], 1))

    if content.ext == "pdf" and content.vector_density >= DENSE_VECTOR_PRIMITIVES and len(content.text.strip()) < 1500:
        hits.append(Hit(DocClass.DRAWING.value, 0.65, "vector_density", f"{content.vector_density} vector primitives on page 1", 1))

    if (content.is_raster or (content.ext in ("jpg", "jpeg", "png"))) and not content.has_text_layer:
        hits.append(Hit(DocClass.OTHER.value, 0.25, "no_text_layer", "no extractable text"))
    return hits


def _filename_hits(filename: str) -> list[Hit]:
    name = _basename(filename)
    hits = []
    for cls, weight, rule, pattern in _FILENAME_RULES:
        m = pattern.search(name)
        if m:
            hits.append(Hit(cls, weight, rule, m.group(0)[:80]))
    return hits


def combine(hits: list[Hit]) -> dict[str, float]:
    remaining: dict[str, float] = {}
    for h in hits:
        remaining[h.doc_class] = remaining.get(h.doc_class, 1.0) * (1.0 - min(max(h.weight, 0.0), 1.0))
    return {cls: min(1.0 - rem, CONFIDENCE_CAP) for cls, rem in remaining.items()}


def classify_rules(content: DocContent, filename: str | None = None) -> RuleOutcome:
    filename = filename or content.filename
    hits = _text_hits(content) + _structure_hits(content) + _filename_hits(filename)
    if not hits:
        hits = [Hit(DocClass.OTHER.value, 0.20, "no_rule_fired", "")]
    scores = combine(hits)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    winner, confidence = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    conflict = runner_up >= CONFLICT_RUNNER_UP

    metadata = extract_metadata(content)
    sub_type = None
    if winner == DocClass.DRAWING.value:
        sub_type = discipline_to_sub_type(metadata.get("discipline"), metadata.get("document_number"), content.dxf_layers)
    evidence = [
        {"rule": h.rule, "class": h.doc_class, "weight": round(h.weight, 3), "matched": h.matched, "page": h.page}
        for h in sorted(hits, key=lambda h: h.weight, reverse=True)
    ]
    return RuleOutcome(winner, sub_type, round(confidence, 3), evidence, metadata, conflict, {k: round(v, 3) for k, v in scores.items()})


def needs_model(outcome: RuleOutcome, confident: float) -> bool:
    return outcome.conflict or outcome.confidence < confident
