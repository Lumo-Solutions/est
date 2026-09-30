"""AI steps of the verification (docs/ai-plan.md §4): interpret BOQ lines, rank the candidate
drawing evidence for each. Both are proposals:

* the ranker may only score candidates it was handed (unknown refs are dropped), so it cannot
  introduce evidence, and the schema has no quantity or action field;
* if the AI is unavailable for a batch (not configured / not allowed / over budget / provider
  down), that batch silently keeps the rules result and the caller records it as 'rules'.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.ai.errors import AIError
from app.ai.gateway import AIGateway, AIMeta
from app.ai.provider import CLASSIFY, MATCH_RANK
from app.takeoff.prompts import load_schema, render_prompt
from app.verification.engine import Candidate, Evidence, Interpretation, LineInput, interpret_by_rules

INTERPRET_BATCH = 25
RANK_BATCH = 8
CONCURRENCY = 4
PROMPT_VERSION = "1"
MAX_KEYWORDS = 6


@dataclass(slots=True)
class AiOutcome:
    ai_used: bool
    unavailable_reason: str | None = None


def _clean_interp(raw: dict, line: LineInput) -> Interpretation:
    fallback = interpret_by_rules(line)
    size = raw.get("size_mm")
    kws = [str(k).lower()[:40] for k in (raw.get("keywords") or [])][:MAX_KEYWORDS]
    interp = Interpretation(
        work_type=(raw.get("work_type") or None) and str(raw["work_type"])[:80],
        material=(raw.get("material") or None) and str(raw["material"])[:60],
        size_mm=float(size) if isinstance(size, (int, float)) and size > 0 else None,
        unit=(raw.get("unit") or None), trade=(raw.get("trade") or None), source="ai", keywords=kws,
    )
    # Anything the model left blank falls back to what the rules read from the text.
    interp.work_type = interp.work_type or fallback.work_type
    interp.material = interp.material or fallback.material
    interp.size_mm = interp.size_mm or fallback.size_mm
    if not interp.keywords:
        interp.keywords = fallback.keywords
    return interp


async def interpret_lines(
    gateway: AIGateway, lines: list[LineInput], parents: dict[str, str], meta: AIMeta
) -> tuple[dict[str, Interpretation], AiOutcome]:
    out = {l.id: interpret_by_rules(l) for l in lines}
    outcome = AiOutcome(False)
    sem = asyncio.Semaphore(CONCURRENCY)
    by_id = {l.id: l for l in lines}

    async def one(batch: list[LineInput]) -> None:
        payload = [
            {"id": l.id, "item_no": l.item_no, "description": l.description, "uom": l.uom, "parent": parents.get(l.id, "")}
            for l in batch
        ]
        system, user = render_prompt("boq_interpret.j2", lines=payload)
        async with sem:
            try:
                res = await gateway.run(
                    task="boq_interpret", kind=CLASSIFY, system=system, user=user,
                    schema=load_schema("boq_interpret.schema.json"), max_tokens=3000,
                    prompt_version=PROMPT_VERSION, meta=meta,
                )
            except AIError as exc:
                outcome.unavailable_reason = exc.code
                return
        outcome.ai_used = True
        for item in res.data.get("lines", []):
            line = by_id.get(item.get("id", ""))
            if line is not None:
                out[line.id] = _clean_interp(item, line)

    todo = [l for l in lines if not_verifiable_skip(l) is False]
    await asyncio.gather(*(one(todo[i : i + INTERPRET_BATCH]) for i in range(0, len(todo), INTERPRET_BATCH)))
    return out, outcome


def not_verifiable_skip(line: LineInput) -> bool:
    """Lines that can never be verified (headings, provisional sums...) are not sent to the model."""
    from app.verification.engine import not_verifiable_reason

    return not_verifiable_reason(line) is not None


async def rank_lines(
    gateway: AIGateway,
    work: list[tuple[LineInput, Interpretation, list[Candidate]]],
    evidence_by_ref: dict[str, Evidence],
    meta: AIMeta,
) -> tuple[dict[str, list[Candidate]], AiOutcome]:
    """Returns line_id -> ranked candidates. Lines whose batch failed keep their rules candidates."""
    result = {line.id: list(cands) for line, _i, cands in work}
    outcome = AiOutcome(False)
    sem = asyncio.Semaphore(CONCURRENCY)
    todo = [w for w in work if w[2]]

    async def one(batch: list[tuple[LineInput, Interpretation, list[Candidate]]]) -> None:
        payload = []
        for line, interp, cands in batch:
            payload.append(
                {
                    "id": line.id, "item_no": line.item_no, "description": line.description, "uom": line.uom,
                    "interpretation": _interp_text(interp),
                    "candidates": [
                        {
                            "ref": c.ref, "kind": evidence_by_ref[c.ref].kind, "label": evidence_by_ref[c.ref].label[:200],
                            "value": round(evidence_by_ref[c.ref].value, 3), "unit": evidence_by_ref[c.ref].unit or "",
                            "layer": evidence_by_ref[c.ref].layer, "sheet": evidence_by_ref[c.ref].page,
                        }
                        for c in cands
                    ],
                }
            )
        system, user = render_prompt("evidence_rank.j2", lines=payload)
        async with sem:
            try:
                res = await gateway.run(
                    task="evidence_rank", kind=MATCH_RANK, system=system, user=user,
                    schema=load_schema("evidence_rank.schema.json"), max_tokens=4000,
                    prompt_version=PROMPT_VERSION, meta=meta,
                )
            except AIError as exc:
                outcome.unavailable_reason = exc.code
                return
        outcome.ai_used = True
        allowed = {line.id: {c.ref for c in cands} for line, _i, cands in batch}
        for entry in res.data.get("lines", []):
            lid = entry.get("id", "")
            if lid not in allowed:
                continue
            ranked: list[Candidate] = []
            seen: set[str] = set()
            for r in entry.get("ranked", []):
                ref = r.get("ref")
                if ref not in allowed[lid] or ref in seen:  # cannot introduce evidence
                    continue
                seen.add(ref)
                score = max(0.0, min(1.0, float(r.get("score") or 0.0)))
                ranked.append(Candidate(ref, score, str(r.get("reason") or "")[:240], "ai", bool(r.get("selected"))))
            # Candidates the model did not mention stay proposals but are not selected.
            for c in next(cands for line, _i, cands in batch if line.id == lid):
                if c.ref not in seen:
                    ranked.append(Candidate(c.ref, c.score * 0.5, c.reason, "ai", False))
            if ranked:
                result[lid] = ranked

    await asyncio.gather(*(one(todo[i : i + RANK_BATCH]) for i in range(0, len(todo), RANK_BATCH)))
    return result, outcome


def _interp_text(i: Interpretation) -> str:
    parts = [p for p in (i.work_type, i.material, f"{int(i.size_mm)}mm" if i.size_mm else None, i.trade) if p]
    return ", ".join(parts)
