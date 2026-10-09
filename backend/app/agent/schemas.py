"""The agent's step contract and the argument model of every tool (docs/boq-agent/plan.md section 3).

The model answers `{note, tool, args}`. `tool` is a fixed enum; `args` is validated here against the tool's pydantic model,
after the gateway has checked the outer shape. Anything invalid goes back to the model as an error result and counts as a
step. Bounds (pages, rows, result sizes) live in these models, not in the prompt.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_PAGES_PER_READ = 5
MAX_SHEET_ROWS = 100
MAX_SEARCH_RESULTS = 20
MAX_LINES_PER_CALL = 50
MAX_NOTE_CHARS = 300


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class BoqLinesArgs(Args):
    section: str = Field(min_length=1, max_length=64, description="section item_no or id from boq_outline")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=MAX_LINES_PER_CALL)


class ListFolderArgs(Args):
    path: str = Field(default="", max_length=512, description="folder path in the pack; empty = the root")


class SearchFilesArgs(Args):
    query: str = Field(min_length=1, max_length=300)
    folder: str | None = Field(default=None, max_length=512)
    ext: str | None = Field(default=None, max_length=8)
    doc_class: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=10, ge=1, le=MAX_SEARCH_RESULTS)


class FileArgs(Args):
    file_id: UUID


class ReadTextArgs(Args):
    file_id: UUID
    first_page: int = Field(default=1, ge=1)
    last_page: int | None = Field(default=None, ge=1)

    @field_validator("last_page")
    @classmethod
    def _span(cls, v: int | None, info: Any) -> int | None:
        first = info.data.get("first_page", 1)
        if v is not None and v < first:
            raise ValueError("last_page must be at least first_page")
        if v is not None and v - first + 1 > MAX_PAGES_PER_READ:
            raise ValueError(f"at most {MAX_PAGES_PER_READ} pages per read")
        return v


class ReadSheetArgs(Args):
    file_id: UUID
    sheet: str | None = Field(default=None, max_length=128)
    first_row: int = Field(default=1, ge=1)
    row_count: int = Field(default=40, ge=1, le=MAX_SHEET_ROWS)


class ViewPageArgs(Args):
    file_id: UUID
    page: int = Field(ge=1)
    question: str = Field(min_length=3, max_length=300, description="what to look for on the page")
    region: list[float] | None = Field(default=None, description="[x0, y0, x1, y1] as fractions of the page, optional")

    @field_validator("region")
    @classmethod
    def _region(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        if len(v) != 4 or not all(0.0 <= x <= 1.0 for x in v) or v[0] >= v[2] or v[1] >= v[3]:
            raise ValueError("region must be [x0, y0, x1, y1] with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
        return v


class LineIdsArgs(Args):
    line_ids: list[UUID] = Field(min_length=1, max_length=20)


class CostCandidatesArgs(Args):
    line_ids: list[UUID] = Field(min_length=1, max_length=10)


class EvidenceItem(Args):
    file_id: UUID
    page: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, max_length=300)
    kind: Literal["text", "table", "drawing", "measurement", "quote", "other"] = "text"


class Estimate(Args):
    rate: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    uom: str | None = Field(default=None, max_length=16)
    method: str = Field(min_length=10, max_length=500)


class ProposeLineArgs(Args):
    line_id: UUID
    candidate_ref: str | None = Field(default=None, max_length=64)
    estimate: Estimate | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=3, max_length=500)
    flags: list[str] = Field(default_factory=list, max_length=6)


class FinishSectionArgs(Args):
    summary: str = Field(min_length=3, max_length=600)


class ExplainLineArgs(Args):
    line_id: UUID


class RerunSectionArgs(Args):
    section: str = Field(min_length=1, max_length=64)
    note: str = Field(min_length=3, max_length=500)


# tool name -> (args model, one-line description for the prompt)
TOOLS: dict[str, tuple[type[Args], str]] = {
    "boq_outline": (NoArgs, "sections of the BOQ with trades, line counts, units and sample descriptions"),
    "boq_lines": (BoqLinesArgs, "the lines of one section (id, item_no, description, uom, quantity)"),
    "list_folder": (ListFolderArgs, "entries under a folder of the tender pack, with rules hints"),
    "search_files": (SearchFilesArgs, "full-text + semantic search over the pack's file index"),
    "file_info": (FileArgs, "the manifest entry of one file (pages, sheets, title block, hints)"),
    "read_text": (ReadTextArgs, "the text of up to 5 pages of a PDF/DOCX file"),
    "read_sheet": (ReadSheetArgs, "rows of a spreadsheet sheet"),
    "view_page": (ViewPageArgs, "look at one page image with the vision model (expensive, capped per run)"),
    "read_title_block": (FileArgs, "drawing number, title, revision, scale from a drawing's title block"),
    "get_measurements": (FileArgs, "measured quantities of a drawing (starts measuring it if needed)"),
    "verify_lines": (LineIdsArgs, "compare BOQ lines with drawing evidence: Match / Variance / Missing / Not verifiable"),
    "cost_candidates": (CostCandidatesArgs, "real cost sources for lines: accepted quotes, cost library, history, with flags"),
    "propose_line": (ProposeLineArgs, "record a cost proposal for one BOQ line (candidate_ref or estimate, with evidence)"),
    "finish_section": (FinishSectionArgs, "close the section with a summary"),
}
CHAT_TOOLS: dict[str, tuple[type[Args], str]] = {
    "run_status": (NoArgs, "progress of the latest run"),
    "explain_line": (ExplainLineArgs, "the evidence and rationale behind a line's proposal"),
    "rerun_section": (RerunSectionArgs, "start a re-run of one section with your note added to its context"),
}
FINISH = "finish_section"
# Counted separately from ordinary steps (cost and time).
VISION_TOOLS = frozenset({"view_page"})
WRITE_TOOLS = frozenset({"propose_line"})


def step_schema(tool_names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["note", "tool", "args"],
        "properties": {
            "note": {"type": "string", "maxLength": MAX_NOTE_CHARS},
            "tool": {"type": "string", "enum": tool_names},
            "args": {"type": "object"},
        },
    }


def validate_args(tool: str, raw: Any, registry: dict[str, tuple[type[Args], str]]) -> tuple[Args | None, str | None]:
    """(args, None) or (None, why it is invalid) -- the why goes back to the model."""
    if tool not in registry:
        return None, f"unknown tool {tool!r}; use one of: {', '.join(sorted(registry))}"
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None, "args must be an object"
    try:
        return registry[tool][0].model_validate(raw), None
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()[:4])
        return None, f"invalid args for {tool}: {problems}"
