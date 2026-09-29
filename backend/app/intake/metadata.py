"""Metadata regexes for tender documents. Every value is a *proposal*; the
review screen lets a lead_estimator edit it before anything is routed."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.intake.extract import DocContent

_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"

_LABELLED_NO = re.compile(
    r"(?:DRAWING|DWG|DOCUMENT|DOC)\s*(?:NO\.?|NUMBER|NUM|#)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-_/.]{1,30})", re.I
)
DOC_NO = re.compile(r"\b([A-Z]{1,4}-\d{2,5}(?:-\d{1,3})?)\b")
_REV = re.compile(r"\bREV(?:ISION)?\b\.?\s*[:\-]?\s*([A-Z]|\d{1,2})\b", re.I)
_REV_FILENAME = re.compile(r"\bREV\.?\s*([A-Z0-9]{1,2})\b", re.I)
_TITLE = re.compile(r"\bTITLE\s*[:\-]\s*(.+)", re.I)
_SCALE = re.compile(r"\bSCALE\s*[:\-]?\s*(1\s*:\s*\d+|NTS|AS SHOWN)", re.I)
_SHEET = re.compile(r"\bSHEET\s*(?:NO\.?\s*)?(\d+)\s*(?:OF|/)\s*(\d+)", re.I)
_DISCIPLINE = re.compile(r"\bDISCIPLINE\s*[:\-]\s*([A-Za-z][A-Za-z &/]{2,30})", re.I)
_DATE = re.compile(
    rf"\b(\d{{1,2}}\s+(?:{_MONTHS})[A-Z]*\.?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})\b", re.I
)
_ADDENDUM_NO = re.compile(r"\bADDEND(?:UM|A)\s*(?:NO\.?|NUMBER|#)?\s*[:.\-]?\s*(\d{1,3})\b", re.I)
_ISSUE_DATE = re.compile(rf"\b(?:ISSUE|ISSUED|DATE)\s*(?:DATE)?\s*[:\-]?\s*(\d{{1,2}}\s+(?:{_MONTHS})[A-Z]*\.?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})", re.I)

_SUPERSEDE_VERBS = re.compile(r"\b(supersed\w+|replac\w+|withdrawn|in lieu of|cancel\w*)\b", re.I)
_AMEND_VERBS = re.compile(r"\b(amend\w*|revis\w+|modif\w+|changed?|updated?)\b", re.I)
_DOC_REF = re.compile(r"\b([A-Z]{1,4}-\d{2,5}(?:-\d{1,3})?)(?:\s*(?:REV(?:ISION)?\.?)\s*([A-Z0-9]{1,2})\b)?", re.I)
_BOQ_MENTION = re.compile(r"\b(?:bill of quantities|schedule of quantities|BOQ)\b", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n+")

_DISCIPLINE_WORDS = (
    ("civil_infra", ("civil", "infra", "road", "drainage", "earthwork", "highway")),
    ("architectural", ("architect",)),
    ("structural", ("structur",)),
    ("mep", ("mep", "mechanical", "electrical", "plumbing", "hvac", "fire fighting", "services")),
    ("landscape", ("landscape",)),
)
_PREFIX_DISCIPLINE = {"C": "civil_infra", "A": "architectural", "S": "structural", "M": "mep", "E": "mep", "P": "mep", "L": "landscape"}


@dataclass(frozen=True, slots=True)
class SupersedeRef:
    reference_text: str  # e.g. "C-101 Rev A" or "BOQ"
    document_number: str | None
    revision: str | None
    action: str  # supersedes | amends


def _first(pattern: re.Pattern[str], text: str, group: int = 1) -> str | None:
    m = pattern.search(text)
    return m.group(group).strip().rstrip(".") if m else None


def parse_date(text: str) -> str | None:
    return _first(_DATE, text)


def normalise_doc_no(value: str | None) -> str | None:
    return re.sub(r"\s+", "", value).upper() if value else None


def discipline_to_sub_type(discipline: str | None, document_number: str | None, layers: list[str] | None = None) -> str | None:
    if discipline:
        low = discipline.lower()
        for sub, words in _DISCIPLINE_WORDS:
            if any(w in low for w in words):
                return sub
    if document_number and document_number[:1].upper() in _PREFIX_DISCIPLINE and "-" in document_number:
        return _PREFIX_DISCIPLINE[document_number[0].upper()]
    for layer in layers or []:
        if len(layer) > 1 and layer[1] == "-" and layer[0].upper() in _PREFIX_DISCIPLINE:
            return _PREFIX_DISCIPLINE[layer[0].upper()]
    return None


def parse_supersede_refs(text: str) -> list[SupersedeRef]:
    """References an addendum says it supersedes or amends, from sentence-level verbs."""
    refs: list[SupersedeRef] = []
    seen: set[tuple[str, str]] = set()
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence.strip():
            continue
        supersedes = bool(_SUPERSEDE_VERBS.search(sentence))
        amends = bool(_AMEND_VERBS.search(sentence))
        if not (supersedes or amends):
            continue
        action = "supersedes" if supersedes else "amends"
        for m in _DOC_REF.finditer(sentence):
            number = normalise_doc_no(m.group(1))
            rev = m.group(2).upper() if m.group(2) else None
            label = f"{number} Rev {rev}" if rev else number
            key = (number or "", action)
            # "supersedes C-101 Rev A. C-101 Rev B is issued" would list Rev B: only the
            # sentence holding the verb counts, and the first ref per number wins.
            if key in seen:
                continue
            seen.add(key)
            refs.append(SupersedeRef(label, number, rev, action))
        if amends and not supersedes and _BOQ_MENTION.search(sentence) and ("BOQ", "amends") not in seen:
            seen.add(("BOQ", "amends"))
            refs.append(SupersedeRef("BOQ", None, None, "amends"))
    return refs


def extract_metadata(content: DocContent) -> dict:
    """All metadata the text/structure supports, absent keys omitted."""
    text = content.text or ""
    block = content.title_block_text or ""
    both = f"{block}\n{text}"
    md: dict = {}

    number = _first(_LABELLED_NO, both)
    if not number:
        m = DOC_NO.search(block) or DOC_NO.search(content.filename) or DOC_NO.search(text[:600])
        number = m.group(1) if m else None
    number = normalise_doc_no(number)
    if number:
        md["document_number"] = number

    rev = _first(_REV, block) or _first(_REV, text[:1500]) or _first(_REV_FILENAME, content.filename)
    if rev:
        md["revision"] = rev.upper()
    if (title := _first(_TITLE, both)):
        md["title"] = title[:200]
    if (scale := _first(_SCALE, both)):
        md["scale"] = re.sub(r"\s+", "", scale).upper() if ":" in scale else scale.upper()
    m = _SHEET.search(both)
    if m:
        md["sheet_number"] = f"{m.group(1)} of {m.group(2)}"
    discipline = _first(_DISCIPLINE, both)
    if discipline:
        md["discipline"] = discipline.strip()
    if (date := parse_date(both)):
        md["date"] = date

    add_no = _first(_ADDENDUM_NO, text[:1200]) or _first(_ADDENDUM_NO, content.filename)
    if add_no:
        md["addendum_number"] = str(int(add_no))
        issue = _first(_ISSUE_DATE, text)
        if issue:
            md["addendum_issue_date"] = issue
        refs = parse_supersede_refs(text)
        if refs:
            md["supersedes"] = [r.reference_text for r in refs if r.action == "supersedes"]
            md["amends"] = [r.reference_text for r in refs if r.action == "amends"]

    best = content.best_sheet
    if best is not None:
        md["sheet_names"] = [s.name for s in content.sheets]
        md["boq_sheet"] = best.name
        md["header_row"] = best.header_row
    return md


_REV_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def revision_sort_key(revision: str | None) -> tuple[int, int]:
    """Orders revisions: none < 0/1/2.. (numeric) < A < B ... ; numeric beats alphabetic ties
    never occur in one lineage in practice, so numeric sorts first."""
    if not revision:
        return (-1, 0)
    rev = revision.strip().upper()
    if rev.isdigit():
        return (0, int(rev))
    if len(rev) == 1 and rev in _REV_ALPHA:
        return (1, _REV_ALPHA.index(rev))
    return (1, sum(_REV_ALPHA.index(c) + 1 for c in rev if c in _REV_ALPHA) + 26)
