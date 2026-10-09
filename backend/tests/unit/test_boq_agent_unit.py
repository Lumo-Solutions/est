"""BOQ agent, unit level (no database, no network): the step contract, tool argument bounds, how sections are cut from a BOQ,
how tool results are shortened, and the mock provider's side of the agent."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent import boq_view
from app.agent.mock_sessions import Script, demo_plan, demo_step, parse_state
from app.agent.schemas import CHAT_TOOLS, TOOLS, step_schema, validate_args
from app.agent.tools import ToolResult, result_text
from app.ai.schema_util import strip_unknown, validate
from app.services.agent import CEILING, _clamp_limits, estimate_run


def _item(no, desc="x", parent=None, qty=None, uom="m", path=None, sort=0):
    return SimpleNamespace(id=uuid.uuid4(), parent_id=parent.id if parent else None, item_no=no, description=desc, uom=uom, boq_quantity=qty,
                           path=path or no.replace(".", "_"), sort_order=sort)


# ------------------------------------------------------------------------------------------------ step contract
def test_step_schema_keeps_args_open_and_names_closed():
    schema = step_schema(list(TOOLS))
    assert schema["properties"]["tool"]["enum"] == list(TOOLS)
    out = strip_unknown({"note": "n", "tool": "boq_outline", "args": {"anything": 1}, "extra": "dropped"}, schema)
    assert out == {"note": "n", "tool": "boq_outline", "args": {"anything": 1}}  # args survive; the gateway's strip does not eat them
    assert validate({"note": "n", "tool": "rm_rf", "args": {}}, schema)  # an unknown tool is a schema problem


@pytest.mark.parametrize(
    "tool,args,fragment",
    [
        ("nope", {}, "unknown tool"),
        ("read_text", {"file_id": str(uuid.uuid4()), "first_page": 1, "last_page": 9}, "at most 5 pages"),
        ("read_text", {"file_id": "not-a-uuid"}, "file_id"),
        ("search_files", {"query": ""}, "query"),
        ("search_files", {"query": "x", "limit": 500}, "limit"),
        ("read_sheet", {"file_id": str(uuid.uuid4()), "row_count": 10_000}, "row_count"),
        ("view_page", {"file_id": str(uuid.uuid4()), "page": 0, "question": "what?"}, "page"),
        ("view_page", {"file_id": str(uuid.uuid4()), "page": 1, "question": "what?", "region": [0.5, 0.5, 0.2, 0.9]}, "region"),
        ("cost_candidates", {"line_ids": []}, "line_ids"),
        ("cost_candidates", {"line_ids": [str(uuid.uuid4())] * 11}, "line_ids"),
        ("propose_line", {"line_id": str(uuid.uuid4()), "confidence": 1.5, "rationale": "because"}, "confidence"),
        ("propose_line", {"line_id": str(uuid.uuid4()), "confidence": 0.5, "rationale": "because", "rate": 1}, "rate"),  # a rate is not an argument
        ("propose_line", {"line_id": str(uuid.uuid4()), "confidence": 0.5, "rationale": "because", "estimate": {"rate": -1, "currency": "AED", "method": "a method here"}}, "rate"),
        ("boq_outline", {"x": 1}, "x"),
        ("finish_section", {}, "summary"),
    ],
)
def test_invalid_args_come_back_as_a_reason(tool, args, fragment):
    parsed, why = validate_args(tool, args, {**TOOLS, **CHAT_TOOLS})
    assert parsed is None and why and fragment in why


def test_valid_args_parse():
    fid = str(uuid.uuid4())
    parsed, why = validate_args("read_text", {"file_id": fid, "first_page": 2, "last_page": 4}, TOOLS)
    assert why is None and parsed.first_page == 2 and parsed.last_page == 4
    parsed, why = validate_args("search_files", {"query": "pipe", "limit": 5}, TOOLS)
    assert why is None and parsed.limit == 5
    parsed, why = validate_args("boq_outline", None, TOOLS)
    assert why is None


def test_chat_tools_only_exist_in_chat_registry():
    assert set(CHAT_TOOLS).isdisjoint(TOOLS)
    parsed, why = validate_args("run_status", {}, TOOLS)
    assert parsed is None and "unknown tool" in why
    # there is no tool that sets money, percentages, FX, quantities or submits
    assert not {n for n in {*TOOLS, *CHAT_TOOLS} if any(w in n for w in ("submit", "approve", "markup", "fx", "quantity", "set_"))}


# ------------------------------------------------------------------------------------------------ sections
def test_sections_are_top_level_groups_with_their_leaf_lines():
    a = _item("1", "Earthworks")
    a1 = _item("1.1", "Excavate", a, 100, "m3", "1_1")
    a2 = _item("1.2", "Backfill", a, 50, "m3", "1_2")
    b = _item("2", "Pipework")
    b1 = _item("2.1", "Pipes", b, None, None, "2_1")  # a sub-heading
    b11 = _item("2.1.1", "300mm pipe", b1, 245, "m", "2_1_1")
    secs = boq_view.build_sections([a, a1, a2, b, b1, b11])
    assert [s.item_no for s in secs] == ["1", "2"]
    assert secs[0].line_ids == [a1.id, a2.id] and secs[1].line_ids == [b11.id]
    assert boq_view.find_section(secs, "2") is secs[1]
    assert boq_view.find_section(secs, str(secs[0].section_item_id)) is secs[0]
    assert boq_view.find_section(secs, "Pipew") is secs[1]
    assert boq_view.find_section(secs, "9") is None


def test_flat_boq_is_chunked():
    items = [_item(f"{i}", f"line {i}", None, 1, "nr", f"l{i}", sort=i) for i in range(1, 95)]
    secs = boq_view.build_sections(items)
    assert [len(s.line_ids) for s in secs] == [40, 40, 14]
    assert all(s.synthetic for s in secs)
    assert sum(len(s.line_ids) for s in secs) == 94


def test_group_with_no_quantities_is_not_a_section():
    g = _item("1", "Preliminaries")
    h = _item("1.1", "Heading only", g, None, None, "1_1")
    assert boq_view.build_sections([g, h]) == []


# ------------------------------------------------------------------------------------------------ results and limits
def test_result_text_is_cut_to_the_limit_and_stays_json():
    big = ToolResult(True, {"pages": [{"page": i, "text": "word " * 2000} for i in range(5)]}, "s")
    s = result_text(big, 3000)
    assert len(s) <= 3000
    assert json.loads(s)["ok"] is True
    small = result_text(ToolResult(True, {"a": 1}, "s"), 3000)
    assert json.loads(small) == {"ok": True, "a": 1}


def test_limits_are_clamped_to_the_ceiling(monkeypatch):
    monkeypatch.setattr("app.services.agent.default_limits", lambda *a, **k: {"max_steps": 40, "max_page_views": 60, "max_usd": 5.0})
    lim = _clamp_limits({"max_steps": 10_000, "max_usd": 1000, "max_page_views": 0, "bogus": 5})
    assert lim["max_steps"] == CEILING["max_steps"] and lim["max_usd"] == CEILING["max_usd"] and lim["max_page_views"] == 1
    assert "bogus" not in lim
    assert _clamp_limits(None) == _clamp_limits({})


def test_estimate_is_free_for_local_providers_and_capped_for_external():
    secs = [boq_view.SectionSpec(uuid.uuid4(), "1", "1 A", [uuid.uuid4() for _ in range(30)])] * 3
    lim = {"max_steps": 40, "max_page_views": 60, "max_usd": 5.0}
    assert estimate_run(secs, lim, provider="mock", model="mock", external=False)["usd"] == 0
    ext = estimate_run(secs, lim, provider="openai_compatible", model="qwen3.7-plus", external=True)
    assert 0 < ext["usd"] <= 5.0 and ext["unverified_price"] is True and ext["steps"] > 0
    capped = estimate_run(secs, {**lim, "max_usd": 0.01}, provider="anthropic", model="claude-sonnet-5-5", external=True)
    assert capped["usd"] == 0.01 and capped["usd_uncapped"] > 0.01


# ------------------------------------------------------------------------------------------------ the mock provider's agent
def _req(state: dict):
    return SimpleNamespace(user=f"head\n<<<STATE>>>{json.dumps(state)}<<<END STATE>>>\nReturn the next tool call.")


def test_state_block_round_trips():
    assert parse_state(_req({"a": 1}).user) == {"a": 1}
    assert parse_state("no block") == {}


def test_demo_policy_searches_reads_fetches_proposes_and_finishes():
    line = str(uuid.uuid4())
    base = {"section": {"label": "1 Earthworks", "lines": 1}, "unproposed": [{"id": line, "item_no": "1.1", "fetched": None}], "files_read": [], "proposed_count": 0}
    assert demo_step(_req({**base, "step": 1, "last": None}))["tool"] == "search_files"
    hit = {"file_id": str(uuid.uuid4()), "ext": "pdf"}
    nxt = demo_step(_req({**base, "step": 2, "last": {"tool": "search_files", "result": {"results": [hit]}}}))
    assert nxt["tool"] == "read_text" and nxt["args"]["file_id"] == hit["file_id"]
    read = {**base, "files_read": [{"file_id": hit["file_id"], "pages": [1]}]}
    assert demo_step(_req({**read, "step": 3, "last": {"tool": "read_text"}}))["tool"] == "cost_candidates"
    fetched = {**read, "unproposed": [{"id": line, "item_no": "1.1", "fetched": {"rules_pick": "q:abc", "candidates": []}}]}
    prop = demo_step(_req({**fetched, "step": 4, "last": {"tool": "cost_candidates"}}))
    assert prop["tool"] == "propose_line" and prop["args"]["candidate_ref"] == "q:abc" and prop["args"]["evidence"][0]["file_id"] == hit["file_id"]
    nothing = {**read, "unproposed": [{"id": line, "item_no": "1.1", "fetched": {"rules_pick": None, "candidates": []}}]}
    assert demo_step(_req({**nothing, "step": 4, "last": {"tool": "cost_candidates"}}))["tool"] == "finish_section"


def test_demo_plan_covers_every_section():
    secs = [{"section_id": str(uuid.uuid4()), "label": f"S{i}"} for i in range(3)]
    plan = demo_plan(_req({"sections": secs}))
    assert [s["section_id"] for s in plan["sections"]] == [s["section_id"] for s in secs]


def test_script_replays_then_finishes_and_records_states():
    script = Script([{"note": "a", "tool": "boq_outline", "args": {}}, lambda st: {"note": "b", "tool": "boq_lines", "args": {"section": st["section"]["item_no"]}}])
    assert script(_req({"step": 1}))["tool"] == "boq_outline"
    assert script(_req({"step": 2, "section": {"item_no": "7"}}))["args"] == {"section": "7"}
    assert script(_req({"step": 3}))["tool"] == "finish_section"
    assert len(script.seen) == 3


def test_decimal_cost_ceiling_is_a_decimal_friendly_number():
    assert Decimal(str(CEILING["max_usd"])) > 0
