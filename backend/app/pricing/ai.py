"""AI steps of the pricing assistant (docs/ai-plan.md §4, Phase 4). Both are proposals.

* choose_costs: for each line, the model scores the candidates it is handed and selects at most one. It
  cannot add a source, and it never outputs a rate: the caller reads the rate from its own candidate.
* advise_markup: percentages and reasoning only; the platform computes every margin figure.
An unavailable AI (not configured / not allowed / budget / provider down) is reported, never fatal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.ai.errors import AIError
from app.ai.gateway import AIGateway, AIMeta
from app.ai.provider import MATCH_RANK, EXTRACT
from app.pricing.engine import CostCandidate, clamp_option
from app.takeoff.prompts import load_schema, render_prompt

CHOOSE_BATCH = 6
CONCURRENCY = 4
PROMPT_VERSION = "1"

# Ranges the schema allows and the platform accepts as advice.
MARKUP_RANGE = (0.0, 40.0)
OVERHEAD_RANGE = (0.0, 30.0)
VOLATILITY_RANGE = (0.0, 20.0)


@dataclass(slots=True)
class ChoiceOutcome:
    ai_used: bool = False
    unavailable_reason: str | None = None


def _age_text(c: CostCandidate, tender_months: float | None) -> str:
    if c.ctype == "historical":
        return f"{c.samples} past observation(s)"
    return f"{tender_months:.0f} months old" if tender_months is not None else ""


async def choose_costs(
    gateway: AIGateway, work: list[dict], cands_by_line: dict[str, list[CostCandidate]], meta: AIMeta
) -> tuple[dict[str, dict], ChoiceOutcome]:
    """work: [{id, item_no, description, uom, quantity}]. Returns line_id -> {ranked:[(ref,score,selected,why)], overall}."""
    out: dict[str, dict] = {}
    outcome = ChoiceOutcome()
    sem = asyncio.Semaphore(CONCURRENCY)
    todo = [w for w in work if cands_by_line.get(w["id"])]

    async def one(batch: list[dict]) -> None:
        payload = []
        for w in batch:
            payload.append(
                {
                    **w,
                    "candidates": [
                        {
                            "ref": c.ref, "type": c.ctype, "label": c.label[:200], "rate": f"{c.rate:,.2f}", "currency": c.currency,
                            "uom": c.uom, "vendor": c.vendor, "age": _age_text(c, c.detail.get("age_months")), "flags": c.flags,
                        }
                        for c in cands_by_line[w["id"]]
                    ],
                }
            )
        system, user = render_prompt("cost_choose.j2", lines=payload)
        async with sem:
            try:
                res = await gateway.run(
                    task="cost_choose", kind=MATCH_RANK, system=system, user=user,
                    schema=load_schema("cost_choose.schema.json"), max_tokens=4000, prompt_version=PROMPT_VERSION, meta=meta,
                )
            except AIError as exc:
                outcome.unavailable_reason = exc.code
                return
        outcome.ai_used = True
        ids = {w["id"] for w in batch}
        for entry in res.data.get("lines", []):
            if entry.get("id") in ids:
                out[entry["id"]] = {
                    "ranked": [
                        (r.get("ref", ""), float(r.get("score") or 0.0), bool(r.get("selected")), str(r.get("rationale") or "")[:400])
                        for r in entry.get("ranked", [])
                    ],
                    "overall": str(entry.get("overall") or "")[:400],
                }

    await asyncio.gather(*(one(todo[i : i + CHOOSE_BATCH]) for i in range(0, len(todo), CHOOSE_BATCH)))
    return out, outcome


async def advise_markup(gateway: AIGateway, context: dict, meta: AIMeta) -> tuple[dict | None, ChoiceOutcome]:
    system, user = render_prompt("markup_advise.j2", **context)
    outcome = ChoiceOutcome()
    try:
        res = await gateway.run(
            task="markup_advise", kind=EXTRACT, system=system, user=user, schema=load_schema("markup_advise.schema.json"),
            max_tokens=3000, prompt_version=PROMPT_VERSION, meta=meta,
        )
    except AIError as exc:
        outcome.unavailable_reason = exc.code
        return None, outcome
    outcome.ai_used = True
    return clean_advice(res.data), outcome


def clean_advice(raw: dict) -> dict:
    """Clamp every percentage into the accepted ranges; a swapped low/high is put right. Nothing in the
    advice is authoritative: it is shown next to values a person sets."""
    options = []
    seen_labels: set[str] = set()
    for o in raw.get("options", []):
        label = o.get("label")
        if label in seen_labels:
            continue
        seen_labels.add(label)
        options.append(
            {
                "label": label,
                "markup_pct": clamp_option(o.get("markup_pct"), *MARKUP_RANGE, 0.0),
                "overhead_pct": clamp_option(o.get("overhead_pct"), *OVERHEAD_RANGE, 0.0),
                "volatility_pct": clamp_option(o.get("volatility_pct"), *VOLATILITY_RANGE, 0.0),
                "rationale": str(o.get("rationale") or "")[:800],
            }
        )
    per_trade = []
    for t in raw.get("per_trade", []):
        lo = clamp_option(t.get("markup_low"), *MARKUP_RANGE, 0.0)
        hi = clamp_option(t.get("markup_high"), *MARKUP_RANGE, lo)
        lo, hi = min(lo, hi), max(lo, hi)
        vlo, vhi = t.get("volatility_low"), t.get("volatility_high")
        per_trade.append(
            {
                "trade": str(t.get("trade") or "")[:120], "markup_low": lo, "markup_high": hi,
                "volatility_low": None if vlo is None else clamp_option(vlo, *VOLATILITY_RANGE, 0.0),
                "volatility_high": None if vhi is None else clamp_option(vhi, *VOLATILITY_RANGE, 0.0),
                "rationale": str(t.get("rationale") or "")[:600],
            }
        )
    return {"options": options, "per_trade": per_trade, "overall": str(raw.get("overall") or "")[:1000]}
