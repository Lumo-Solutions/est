"""The synthetic demo pack + the mock AI + the verification engine give exactly the designed report
(deliberate matches, variances, gaps, not-verifiable lines, and the pipe the BOQ forgot). In memory: no DB."""

from __future__ import annotations

import uuid

import pytest

from app.ai import eval as ai_eval
from app.ai.gateway import AIGateway, AIMeta
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.context import system_context
from app.demo import ai_demo as demo
from app.services.verification import compute_all
from app.verification import ai as vai
from app.verification.engine import LineInput, generate_candidates, interpret_by_rules

S = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
             VLLM_API_BASE="http://vllm.internal:8000/v1", AI_PROVIDER="mock")


def _all_lines() -> list[LineInput]:
    kids = {b.item_no.rsplit(".", 1)[0] for b in demo.BOQ if "." in b.item_no}
    return [
        LineInput(id=b.item_no, item_no=b.item_no, description=b.description, uom=b.uom, quantity=b.qty,
                  is_heading=b.qty is None and b.item_no in kids)
        for b in demo.BOQ
    ]


async def _report(use_ai: bool):
    lines, evidence = _all_lines(), ai_eval._demo_evidence()
    by_ref = {e.ref: e for e in evidence}
    interps = {l.id: interpret_by_rules(l) for l in lines}
    cands = {l.id: generate_candidates(l, interps[l.id], evidence) for l in lines}
    ai_ranked: set[str] = set()
    if use_ai:
        gw = AIGateway(settings=S, store=MemoryStore(), ctx=system_context(uuid.uuid4()))
        meta = AIMeta(entity_type="test", entity_id="demo")
        interps, _ = await vai.interpret_lines(gw, lines, {}, meta)
        work = [(l, interps[l.id], cands[l.id]) for l in lines if not vai.not_verifiable_skip(l)]
        ranked, _ = await vai.rank_lines(gw, work, by_ref, meta)
        cands = {**cands, **ranked}
        ai_ranked = {lid for lid, cs in ranked.items() if any(c.source == "ai" for c in cs)}
    results, missing = compute_all(lines, interps, cands, evidence, {}, ai_ranked)
    return {r.line_id: r for r in results}, missing


async def test_mock_ai_reproduces_the_designed_report():
    by_line, missing = await _report(use_ai=True)
    got = {b.item_no: by_line[b.item_no].vclass for b in demo.BOQ if b.expected}
    assert got == demo.EXPECTED_CLASSES, {k: (v, demo.EXPECTED_CLASSES[k]) for k, v in got.items() if v != demo.EXPECTED_CLASSES[k]}
    # the deliberate numbers
    assert by_line["2.2"].delta_pct == pytest.approx(50.0) and by_line["2.2"].method == "measured"
    assert by_line["5.2"].delta_pct == pytest.approx(15.0) and by_line["5.2"].method == "annotated"
    assert by_line["2.3"].method == "annotated" and by_line["2.1"].method == "measured" and by_line["2.1"].drawing_quantity == 246.0
    # the pipe the BOQ forgot, and nothing else
    assert [m.evidence[0].ref for m in missing] == ["g:storm450"] and missing[0].drawing_quantity == 80.0
    # nothing the AI mapped is attached to two BOQ lines' worth of the same quantity (no double counting)
    assert by_line["1.3"].drawing_quantity is None and by_line["4.1"].drawing_quantity is None


async def test_rules_only_is_a_safe_but_weaker_fallback():
    """Without the AI the built-in rules still produce a valid report; wrongly-mapped lines are flagged 'rules_only'
    so a person knows to check them, and nothing invented is counted."""
    by_line, missing = await _report(use_ai=False)
    assert all(r.vclass in {"match", "variance", "missing_in_drawings", "not_verifiable"} for r in by_line.values())
    attached = [r for r in by_line.values() if r.evidence]
    assert attached and all("rules_only" in r.flags for r in attached)
    assert by_line["6.1"].vclass == "not_verifiable" and by_line["6.2"].vclass == "not_verifiable"
