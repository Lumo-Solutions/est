"""`make ai-smoke`: one tiny REAL call per AI task, to prove a freshly configured provider works end to end
(auth, model, schema-constrained output). Skipped, with a clear message, when no external provider is
configured. Costs a few cents; sends only synthetic one-line inputs, never tenant data.

    python -m app.ai.smoke
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid

from app.ai.gateway import AIGateway
from app.ai.pricing import is_unverified
from app.ai.provider import CLASSIFY, EXTRACT, MATCH_RANK, VISION
from app.ai.registry import resolve_model
from app.ai.store import MemoryStore
from app.core.config import get_settings
from app.core.context import system_context
from app.takeoff.prompts import load_schema, render_prompt

# (task, kind, template, schema file, template variables). Inputs are one line each.
_CASES = [
    ("intake_classify", CLASSIFY, "document_classification.j2", "document_classification.schema.json",
     dict(filename="Bill of Quantities.xlsx", folder_path="02 BOQ", document_text="BILL OF QUANTITIES\nItem Description Unit Qty", title_block_text="", has_image=False, candidates=[])),
    ("boq_pdf_rows", VISION, "boq_pdf_rows.j2", "boq_pdf_rows.schema.json",
     dict(page_number=1, page_text="1.1 Excavate in soil m3 100", has_image=False)),
    ("drawing_annotations", VISION, "drawing_annotations.j2", "drawing_annotations.schema.json",
     dict(page_number=1, sheet_text="DRAWING NO: C-1\nL=45.0m 300mm uPVC\n4 nos MANHOLE", has_image=False)),
    ("boq_interpret", CLASSIFY, "boq_interpret.j2", "boq_interpret.schema.json",
     dict(lines=[{"id": "1", "item_no": "1.1", "description": "Supply and lay 300mm uPVC sewer pipe", "uom": "m", "parent": ""}])),
    ("evidence_rank", MATCH_RANK, "evidence_rank.j2", "evidence_rank.schema.json",
     dict(lines=[{"id": "1", "item_no": "1.1", "description": "Supply and lay 300mm uPVC sewer pipe", "uom": "m", "interpretation": "pipe, uPVC, 300mm",
                  "candidates": [{"ref": "m:a", "kind": "measurement", "label": "pipe layer=SEWER-300", "value": 246.0, "unit": "m", "layer": "SEWER-300", "sheet": 1}]}])),
    ("cost_choose", MATCH_RANK, "cost_choose.j2", "cost_choose.schema.json",
     dict(lines=[{"id": "1", "item_no": "1.1", "description": "Supply and lay 300mm uPVC sewer pipe", "uom": "m", "quantity": "245",
                  "candidates": [{"ref": "c:1", "type": "library", "label": "uPVC SN8 sewer pipe 300mm supply and lay", "rate": "96.00", "currency": "AED", "uom": "m", "vendor": None, "age": "", "flags": []}]}])),
    ("markup_advise", EXTRACT, "markup_advise.j2", "markup_advise.schema.json",
     dict(project={"name": "Smoke", "size_band": "small", "currency": "AED"}, settings={"plant_pct": 0, "overhead_pct": 5, "volatility_pct": 3, "markup_pct": 8},
          trades=[], history=[], totals={"direct_cost": "1,000,000", "lines": 10, "flagged_lines": 0, "unresolved_lines": 0})),
]


async def run_smoke() -> int:
    settings = get_settings()
    gw = AIGateway(settings=settings, store=MemoryStore(external_allowed=True), ctx=system_context(uuid.uuid4()))
    if not gw.provider.external:
        print(f"SKIPPED: AI_PROVIDER={settings.ai_provider!r} is not an external provider, so there is no real key to smoke-test. "
              "Set AI_PROVIDER=anthropic (or openai_compatible), AI_API_KEY and AI_MODEL in deploy/.env, recreate the containers and run again.")
        return 0
    if not gw.provider.is_configured():
        print("SKIPPED: an external provider is selected but AI_API_KEY / AI_MODEL are not set. Fill them in deploy/.env and run again.")
        return 0
    failures = 0
    for task, kind, template, schema_file, variables in _CASES:
        system, user = render_prompt(template, **variables)
        started = time.monotonic()
        try:
            res = await gw.run(task=f"smoke_{task}", kind=kind, system=system, user=user, schema=load_schema(schema_file), max_tokens=800)
            expected = resolve_model(settings, gw.provider.name, kind)
            routed = "" if (expected in res.model or res.model in expected) else f"  <-- ROUTING: expected {expected}"
            unverified = "  (price UNVERIFIED)" if is_unverified(res.model) else ""
            print(f"OK    {task:<22} {int((time.monotonic() - started) * 1000):>6} ms  model={res.model}  est. ${res.cost_usd:.5f}{unverified}{routed}")
            if routed:
                failures += 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {task:<22} {type(exc).__name__}: {exc}")
    print("all tasks OK" if not failures else f"{failures} task(s) failed")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(run_smoke())


if __name__ == "__main__":
    sys.exit(main())
