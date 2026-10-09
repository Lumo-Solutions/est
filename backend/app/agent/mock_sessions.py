"""The mock provider's side of the agent (tests and the keyless dev stack).

* ``demo_step`` is a small deterministic policy: it reads the STATE block the loop puts in the prompt and does what a sensible
  agent would -- search the pack for the section, read the best hit, ask for cost candidates for the lines, propose the rules'
  pick for each line that has one, and finish. It is not a model and claims no quality.
* ``Script`` replays a fixed sequence of steps for a test (callables get the parsed STATE, so they can use real line and file
  ids), which is how the loop, tool validation, limits, injection handling and the settlement fill are exercised without a key.
Everything here is stdlib-only: ``mock_fixtures`` imports it into the provider's default handlers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

_STATE = re.compile(r"<<<STATE>>>(.*)<<<END STATE>>>", re.S)
BATCH = 4


def parse_state(user: str) -> dict[str, Any]:
    m = _STATE.search(user)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _step(note: str, tool: str, args: dict | None = None) -> dict:
    return {"note": note[:300], "tool": tool, "args": args or {}}


def demo_step(req: Any) -> dict:
    st = parse_state(req.user)
    if not st:
        return _step("no state", "finish_section", {"summary": "Nothing to do."})
    section = st.get("section", {})
    last = st.get("last") or {}
    unproposed = st.get("unproposed", [])
    files_read = st.get("files_read", [])
    ev = [{"file_id": f["file_id"], "page": (f.get("pages") or [1])[0] or 1, "kind": "text"} for f in files_read[:1]]

    if not last:
        return _step("Look for documents about this section.", "search_files", {"query": section.get("label", "")[:200], "limit": 5})
    if last.get("tool") == "search_files" and not files_read:
        hits = (last.get("result") or {}).get("results") or []
        for h in hits:
            if h.get("ext") in ("pdf", "docx"):
                return _step("Read the best matching document.", "read_text", {"file_id": h["file_id"], "first_page": 1, "last_page": 2})
            if h.get("ext") in ("xlsx", "csv"):
                return _step("Read the best matching sheet.", "read_sheet", {"file_id": h["file_id"], "row_count": 20})
    fetched = [u for u in unproposed if u.get("fetched") is not None]
    with_pick = [u for u in fetched if (u["fetched"] or {}).get("rules_pick")]
    if with_pick:
        u = with_pick[0]
        pick = u["fetched"]["rules_pick"]
        return _step(
            f"Propose the best source for {u.get('item_no')}.", "propose_line",
            {"line_id": u["id"], "candidate_ref": pick, "evidence": ev, "confidence": 0.8, "rationale": "Best-matching real cost source for this line."},
        )
    not_fetched = [u for u in unproposed if u.get("fetched") is None]
    if not_fetched:
        return _step("Get cost sources for the next lines.", "cost_candidates", {"line_ids": [u["id"] for u in not_fetched[:BATCH]]})
    return _step("Every line was looked at.", "finish_section", {"summary": f"Proposed {st.get('proposed_count', 0)} of {section.get('lines', 0)} lines; the rest have no cost source."})


def demo_plan(req: Any) -> dict:
    st = parse_state(req.user)
    return {
        "summary": "Read the specification and schedules that match each section's title.",
        "sections": [{"section_id": s["section_id"], "folders": [], "queries": [s.get("label", "")[:150]], "why": "title match"} for s in st.get("sections", [])],
    }


def demo_vision(req: Any) -> dict:
    return {"answer": "The page shows a title block and a schedule; no values relevant to the question were legible.", "values": []}


class Script:
    """A fixed sequence of steps: item k is a dict, or a callable(state) -> dict. After the end it finishes the section."""

    def __init__(self, steps: list[dict | Callable[[dict], dict]]) -> None:
        self.steps = steps
        self.seen: list[dict] = []  # the parsed STATE of every call (for assertions)

    def __call__(self, req: Any) -> dict:
        st = parse_state(req.user)
        self.seen.append(st)
        k = max(0, int(st.get("step", 1)) - 1)
        if k >= len(self.steps):
            return _step("done", "finish_section", {"summary": "Script ended."})
        item = self.steps[k]
        return item(st) if callable(item) else item


HANDLERS: dict[str, Callable[[Any], dict]] = {"agent.step": demo_step, "agent.plan": demo_plan, "agent.vision": demo_vision}
