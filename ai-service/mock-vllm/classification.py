"""Deterministic stand-in for the real model's document classification.

Keyword driven on purpose, and independent of the backend's stage 1 rules
(different table, different signals), so the mock is not simply the rules
run twice. It looks at the FILENAME and the text between the DOCUMENT
markers, ignores anything that reads like an instruction, and returns a
plausible confidence. Used by mock-vllm's chat handler for schema title
"DocumentClassification", and imported directly by the backend accuracy test.
"""

from __future__ import annotations

import re

_TEXT_CUES: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("addendum", ("addendum no", "addendum #", "this addendum"), 0.82),
    ("boq", ("bill of quantities", "schedule of quantities", "unit rate"), 0.78),
    ("contract", ("conditions of contract", "particular conditions", "fidic"), 0.80),
    ("tender_instructions", ("instructions to tenderers", "instructions to bidders"), 0.80),
    ("tender_forms", ("form of tender", "bid bond", "performance bond"), 0.80),
    ("clarification", ("request for information", "rfi no", "response to query", "clarification no"), 0.78),
    ("programme", ("programme", "gantt", "baseline schedule", "activity"), 0.70),
    ("site_investigation", ("geotechnical", "borehole", "soil investigation"), 0.82),
    ("specification", ("part 1 general", "specification", "section 0", "section 1", "section 2"), 0.72),
    ("correspondence", ("dear sirs", "dear sir", "yours faithfully", "further to our", "kind regards"), 0.72),
    ("drawing", ("drawing no", "drawing number", "scale 1:", "sheet 1 of", "title block", "general arrangement"), 0.75),
)
_FILENAME_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("addendum", ("add-", "addendum")),
    ("boq", ("boq", "bill_of", "bill of")),
    ("drawing", ("dwg", ".dxf", " rev ")),
    ("specification", ("spec",)),
    ("contract", ("contract", "conditions")),
    ("tender_instructions", ("itt", "instructions")),
    ("tender_forms", ("form_of", "bond")),
    ("clarification", ("rfi", "clarification")),
    ("programme", ("programme", "prog")),
    ("site_investigation", ("geotech", "soil")),
    ("correspondence", ("letter", "email")),
)
_DISCIPLINE = (
    ("structural", ("structural", "reinforcement", "foundation", "slab")),
    ("civil_infra", ("civil", "road", "drainage", "grading", "earthwork", "infrastructure")),
    ("architectural", ("architectural", "floor plan", "elevation", "ceiling")),
    ("mep", ("mechanical", "electrical", "plumbing", "hvac", "mep")),
    ("landscape", ("landscape", "planting")),
)

_DOC_BLOCK = re.compile(r"<<<DOCUMENT TEXT\n(.*?)\nDOCUMENT TEXT>>>", re.S)
_TB_BLOCK = re.compile(r"<<<DOCUMENT TITLE BLOCK\n(.*?)\nDOCUMENT TITLE BLOCK>>>", re.S)
_FILENAME = re.compile(r"^Filename:\s*(.+)$", re.M)
_NUMBER = re.compile(r"\b([A-Z]{1,4}-\d{2,5})\b")
_REV = re.compile(r"\bREV(?:ISION)?\.?\s*[:\-]?\s*([A-Z]|\d{1,2})\b", re.I)
_ADD_NO = re.compile(r"ADDENDUM\s*(?:NO\.?|#)?\s*(\d{1,3})", re.I)
_REF = re.compile(r"\b([A-Z]{1,4}-\d{2,5})(?:\s+REV\.?\s*([A-Z0-9]{1,2}))?", re.I)


def _blocks(user_text: str) -> tuple[str, str, str]:
    fn = _FILENAME.search(user_text)
    doc = _DOC_BLOCK.search(user_text)
    tb = _TB_BLOCK.search(user_text)
    return (fn.group(1).strip() if fn else "", doc.group(1) if doc else "", tb.group(1) if tb else "")


def classify_document(user_text: str, has_image: bool = False) -> dict:
    filename, body, block = _blocks(user_text)
    text = f"{block}\n{body}"
    low = text.lower()
    fname = filename.lower()

    scores: dict[str, float] = {}
    quote: str | None = None
    for cls, cues, conf in _TEXT_CUES:
        for cue in cues:
            idx = low.find(cue)
            if idx >= 0:
                # Earlier in the document counts for more (a title beats a passing mention).
                bonus = 0.08 if idx < 200 else 0.0
                scores[cls] = max(scores.get(cls, 0.0), min(conf + bonus, 0.95))
                if quote is None or conf >= 0.78:
                    quote = text[max(0, idx): idx + 120].strip().splitlines()[0][:180]
                break
    for cls, cues in _FILENAME_CUES:
        if any(c in fname for c in cues):
            # A filename agreeing with a text cue nudges it up; on its own it is weak evidence.
            scores[cls] = min(scores[cls] + 0.05, 0.95) if cls in scores else 0.55

    if scores:
        doc_class, confidence = max(scores.items(), key=lambda kv: kv[1])
    elif has_image or not text.strip():
        doc_class, confidence = "drawing", 0.55  # an image-only page in a tender pack is most often a scanned drawing
    else:
        doc_class, confidence = "other", 0.50

    sub_type = None
    if doc_class == "drawing":
        sub_type = "other"
        for sub, cues in _DISCIPLINE:
            if any(c in low or c in fname for c in cues):
                sub_type = sub
                break
        number = _NUMBER.search(text) or _NUMBER.search(filename)
        if sub_type == "other" and number:
            sub_type = {"C": "civil_infra", "A": "architectural", "S": "structural", "M": "mep", "E": "mep", "P": "mep", "L": "landscape"}.get(number.group(1)[0], "other")

    metadata: dict = {"supersedes": [], "sheet_names": []}
    number = _NUMBER.search(block) or _NUMBER.search(body) or _NUMBER.search(filename)
    if number and doc_class in ("drawing", "addendum", "specification", "clarification"):
        metadata["document_number"] = number.group(1).upper()
    if (rev := _REV.search(text) or _REV.search(filename)) and doc_class == "drawing":
        metadata["revision"] = rev.group(1).upper()
    if doc_class == "addendum":
        if (m := _ADD_NO.search(text) or _ADD_NO.search(filename)):
            metadata["addendum_number"] = str(int(m.group(1)))
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            if re.search(r"supersed|replac|withdrawn|amend", sentence, re.I):
                for ref in _REF.finditer(sentence):
                    label = ref.group(1).upper() + (f" Rev {ref.group(2).upper()}" if ref.group(2) else "")
                    if label not in metadata["supersedes"]:
                        metadata["supersedes"].append(label)

    return {
        "doc_class": doc_class,
        "sub_type": sub_type,
        "confidence": round(confidence, 2),
        "evidence_quote": quote,
        "evidence_page": 1 if quote else None,
        "metadata": {
            "document_number": metadata.get("document_number"),
            "title": None,
            "revision": metadata.get("revision"),
            "date": None,
            "discipline": None,
            "sheet_number": None,
            "scale": None,
            "addendum_number": metadata.get("addendum_number"),
            "addendum_issue_date": None,
            "supersedes": metadata["supersedes"],
            "sheet_names": [],
            "header_row": None,
        },
    }
