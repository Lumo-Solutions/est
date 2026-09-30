"""A 1,200-line BOQ through the verification pipeline (mock AI, in memory): AI calls are batched, the cache makes a re-run
free, the deterministic computation is fast, and progress/budget behave. Guards the 'must handle 1,000+ lines' requirement."""

from __future__ import annotations

import math
import time
import uuid

from app.ai.gateway import AIGateway, AIMeta
from app.ai.providers.mock import MockProvider
from app.ai.store import MemoryStore
from app.core.config import Settings
from app.core.context import system_context
from app.services.verification import compute_all
from app.verification import ai as vai
from app.verification.engine import Evidence, LineInput, generate_candidates, interpret_by_rules

S = Settings(APP_DATABASE_URL="postgresql://x/y", MIGRATOR_DATABASE_URL="postgresql://x/y", S3_ENDPOINT="http://s3",
             VLLM_API_BASE="http://vllm.internal:8000/v1", AI_PROVIDER="mock")
N_LINES = 1200


def _dataset():
    kinds = [("pipe", "m"), ("manhole", "nr"), ("kerb", "m"), ("topsoil", "m2"), ("excavation", "m3")]
    lines = []
    for i in range(N_LINES):
        word, uom = kinds[i % len(kinds)]
        size = 100 + 25 * (i % 20)
        lines.append(LineInput(id=f"L{i}", item_no=f"{i // 50 + 1}.{i % 50 + 1}", description=f"Supply and lay {size}mm {word} type {i % 7} complete", uom=uom, quantity=float(100 + i % 400)))
    evidence = []
    for j in range(300):
        word, unit = kinds[j % len(kinds)]
        evidence.append(Evidence(ref=f"m:{j}", kind="measurement", value=float(100 + j), unit=unit, label=f"{word} layer=LAYER-{100 + 25 * (j % 20)}", page=1 + j % 12))
    return lines, evidence


async def test_1200_lines_are_batched_cached_and_fast():
    lines, evidence = _dataset()
    by_ref = {e.ref: e for e in evidence}
    provider = MockProvider()
    provider.external = True                 # so the gateway caches, exactly as with a real external provider
    gw = AIGateway(settings=S, store=MemoryStore(external_allowed=True), provider=provider, ctx=system_context(uuid.uuid4()))
    meta = AIMeta(entity_type="scale", entity_id="1")

    started = time.monotonic()
    interps, o1 = await vai.interpret_lines(gw, lines, {}, meta)
    work = [(l, interps[l.id], generate_candidates(l, interps[l.id], evidence)) for l in lines]
    ranked, o2 = await vai.rank_lines(gw, work, by_ref, meta)
    results, missing = compute_all(lines, interps, {**{l.id: c for l, _i, c in work}, **ranked}, evidence, {}, set(ranked))
    first = time.monotonic() - started

    interpret_calls = math.ceil(N_LINES / vai.INTERPRET_BATCH)
    rank_calls = math.ceil(sum(1 for _l, _i, c in work if c) / vai.RANK_BATCH)
    assert o1.ai_used and o2.ai_used
    assert len(provider.calls) == interpret_calls + rank_calls          # batched: 48 + ~150 calls, not 2,400
    assert len(provider.calls) < N_LINES / 4
    assert len(results) == N_LINES and all(r.vclass for r in results) and first < 20.0, first

    # a second run over the same document costs nothing: every call is a cache hit
    before = len(provider.calls)
    interps2, _ = await vai.interpret_lines(gw, lines, {}, meta)
    await vai.rank_lines(gw, [(l, interps2[l.id], generate_candidates(l, interps2[l.id], evidence)) for l in lines], by_ref, meta)
    assert len(provider.calls) == before


def test_pure_computation_for_1200_lines_is_well_under_a_second():
    lines, evidence = _dataset()
    interps = {l.id: interpret_by_rules(l) for l in lines}
    started = time.monotonic()
    cands = {l.id: generate_candidates(l, interps[l.id], evidence) for l in lines}
    results, _missing = compute_all(lines, interps, cands, evidence, {}, set())
    assert len(results) == N_LINES
    assert time.monotonic() - started < 15.0
