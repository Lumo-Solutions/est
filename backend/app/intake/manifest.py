"""The file manifest entry: everything that can be read from a file without a model (docs/boq-agent/plan.md §2).

Pure: bytes/DocContent in, ``ManifestEntry`` out. No network, no S3, no database. The rules' classification rides
along as *hints* (with their confidence); it is not a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.intake.extract import DocContent
from app.intake.rules import RuleOutcome

PAGE1_TEXT_CHARS = 4_000
TITLE_BLOCK_CHARS = 2_000
EMBED_TEXT_CHARS = 500
MAX_SHEETS = 12
HEADER_CHARS = 300


@dataclass(slots=True)
class ManifestEntry:
    path: str
    folder: str
    filename: str
    ext: str
    size_bytes: int
    sha256: str
    page_count: int | None = None
    page_sizes: list[list[float]] = field(default_factory=list)
    page1_text: str = ""
    title_block_text: str = ""
    sheets: list[dict] = field(default_factory=list)
    hints: dict = field(default_factory=dict)
    hints_text: str = ""
    partial_index: bool = False
    partial_reason: str | None = None

    def embedding_text(self) -> str:
        title = (self.hints.get("title") or "") if self.hints else ""
        return f"{self.filename} {title} {self.page1_text[:EMBED_TEXT_CHARS]}".strip()


def _hints(rules: RuleOutcome | None) -> tuple[dict, str]:
    if rules is None:
        return {}, ""
    md = rules.metadata or {}
    hints = {
        "doc_class": rules.doc_class,
        "sub_type": rules.sub_type,
        "confidence": rules.confidence,
        "conflict": rules.conflict,
        "candidates": rules.candidates,
        "discipline": md.get("discipline"),
        "document_number": md.get("document_number"),
        "revision": md.get("revision"),
        "scale": md.get("scale"),
        "title": md.get("title"),
        "addendum_number": md.get("addendum_number") or md.get("addendum_no"),
    }
    hints = {k: v for k, v in hints.items() if v not in (None, "", [], {})}
    text = " ".join(
        str(hints[k]) for k in ("doc_class", "sub_type", "discipline", "document_number", "revision", "title", "addendum_number") if k in hints
    )
    return hints, text


def _sheets(content: DocContent) -> list[dict]:
    out = []
    for s in content.sheets[:MAX_SHEETS]:
        out.append(
            {
                "name": s.name,
                "header_row": s.header_row,
                "header": " | ".join(s.columns)[:HEADER_CHARS] if s.columns else (s.sample_text.split("\n", 1)[0][:HEADER_CHARS]),
                "rows": s.row_count,
            }
        )
    return out


def build_entry(
    *, content: DocContent, rules: RuleOutcome | None, filename: str, folder: str, path: str, size_bytes: int, sha256: str,
    partial_reason: str | None = None,
) -> ManifestEntry:
    """``content`` may be an empty DocContent (unreadable or timed-out file): the entry still exists, flagged partial."""
    partial = partial_reason or (f"could not be read fully: {content.error}"[:255] if content.error else None)
    first_page = (content.page_texts[0] if content.page_texts else content.text) or ""
    hints, hints_text = _hints(rules)
    return ManifestEntry(
        path=path,
        folder=folder,
        filename=filename,
        ext=content.ext,
        size_bytes=size_bytes,
        sha256=sha256,
        page_count=content.pages,
        page_sizes=list(content.page_sizes),
        page1_text=first_page[:PAGE1_TEXT_CHARS],
        title_block_text=(content.title_block_text or "")[:TITLE_BLOCK_CHARS],
        sheets=_sheets(content),
        hints=hints,
        hints_text=hints_text,
        partial_index=partial is not None,
        partial_reason=partial,
    )
