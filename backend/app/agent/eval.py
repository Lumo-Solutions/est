"""Evaluation harness for the BOQ agent (docs/boq-agent/plan.md; `make agent-eval`, `make agent-smoke`).

    python -m app.agent.eval --project AI-DEMO-E2E-XXXX --provider mock  --out /tmp/agent-eval
    python -m app.agent.eval --project AI-DEMO-E2E-XXXX --provider configured --budget 1.0 --confirm --out /tmp/agent-smoke

Runs one agent run in this process (no Celery) on a project that already has a BOQ and an uploaded pack, builds the project's
manifest if it has none (documents are not changed), fills the project's draft settlement, and reports:
files read / files in the pack, time to a filled draft, steps, page views, cost per step and per section, proposals, lines
without evidence, and the limit checks. `--provider mock` is deterministic and free (the assertions are the regression test);
`--provider configured` uses the AI provider in the environment and refuses to start without `--confirm` (it spends money),
capping the run at `--budget` USD.

Dev / test only: it acts as a synthetic managing director so it can see any project of the demo tenant.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import time
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.context import RequestContext, system_context
from app.db.session import session_scope

EVAL_USER = uuid.UUID("00000000-0000-0000-0000-00000000a6e1")


def _check(checks: list[dict], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})


async def run_eval(project_code: str, provider: str, budget: float, max_steps: int, confirm: bool, new_draft: bool) -> dict:
    from app.agent import chat, runner  # noqa: F401
    from app.models.agent import AgentLineProposal, AgentRun, AgentRunSection, AgentStep
    from app.models.tenancy import Project
    from app.models.tender_intake import ProjectFileIndex
    from app.services import agent as svc
    from app.services import manifest_backfill

    settings = get_settings()
    app_env = getattr(settings, "app_env", "dev")
    if str(app_env) not in ("dev", "test"):
        raise SystemExit("agent eval is for dev/test only")
    tenant_id = uuid.UUID(settings.demo_tenant_id)
    sys_ctx = system_context(tenant_id)
    user = RequestContext(tenant_id=tenant_id, user_id=EVAL_USER, sub="agent-eval", roles=frozenset({"managing_director"}), is_system=False)

    if provider == "mock":
        from app.ai.factory import set_gateway_override
        from app.ai.gateway import AIGateway
        from app.ai.providers.mock import MockProvider
        from app.ai.store import MemoryStore

        set_gateway_override(lambda s: AIGateway(settings=s, store=MemoryStore(), provider=MockProvider(), ctx=user))

    async with session_scope(sys_ctx) as session:
        project_id = (await session.execute(select(Project.id).where(Project.code == project_code))).scalar_one_or_none()
    if project_id is None:
        raise SystemExit(f"no project with code {project_code!r}")

    stats = await manifest_backfill.backfill_tenant(tenant_id, project_id=project_id)
    queue: list[tuple[str, uuid.UUID, uuid.UUID]] = []

    def enqueue(kind, run_id, tid):
        queue.append((kind, run_id, tid))

    limits = {"max_steps": max_steps, "max_usd": budget}
    async with session_scope(user) as session:
        run = await svc.create_run(session, user, project_id, limits=limits, create_draft=new_draft, enqueue=enqueue)
        run_id, status, estimate = run.id, run.status, run.estimate
    out: dict = {"project": project_code, "provider": provider, "estimate": estimate, "manifest_backfill": asdict(stats), "limits": limits}
    if status == "awaiting_confirm":
        if not confirm:
            raise SystemExit(f"this run would use an external provider (estimate {estimate}); pass --confirm to spend up to {budget} USD")
        async with session_scope(user) as session:
            await svc.confirm_run(session, user, run_id, enqueue=enqueue)

    t0 = time.monotonic()
    guard = 0
    while queue and guard < 400:
        guard += 1
        kind, rid, tid = queue.pop(0)
        if kind == "plan":
            await runner.plan_run(rid, tid, enqueue)
        elif kind == "section":
            await runner.run_next_section(rid, tid, enqueue)
    elapsed = time.monotonic() - t0

    async with session_scope(user) as session:
        run = (await session.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        secs = list((await session.execute(select(AgentRunSection).where(AgentRunSection.run_id == run_id).order_by(AgentRunSection.seq))).scalars())
        steps = list((await session.execute(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq))).scalars())
        props = list((await session.execute(select(AgentLineProposal).where(AgentLineProposal.run_id == run_id))).scalars())
        files_in_pack = (await session.execute(select(func.count()).select_from(ProjectFileIndex).where(ProjectFileIndex.project_id == project_id))).scalar_one()
        per_section = {s.label: {"status": s.status, "steps": s.steps, "stop_reason": s.stop_reason, "coverage": s.coverage} for s in secs}
        cost_by_section: dict[str, float] = {}
        names = {s.id: s.label for s in secs}
        for st in steps:
            label = names.get(st.section_id, "plan/other")
            cost_by_section[label] = cost_by_section.get(label, 0.0) + float(st.cost_usd)
        out.update(
            run_id=str(run_id), status=run.status, error=run.error, seconds=round(elapsed, 1), steps=run.steps_total, page_views=run.page_views,
            ai_calls=run.ai_calls, cost_usd=float(run.cost_usd),
            cost_per_step_usd=round(float(run.cost_usd) / run.steps_total, 6) if run.steps_total else None, cost_by_section=cost_by_section,
            sections=per_section, files_in_pack=int(files_in_pack), summary=run.summary, plan_summary=(run.plan or {}).get("summary"),
            proposals=len([p for p in props if p.status in ("proposed", "applied")]), applied=len([p for p in props if p.status == "applied"]),
            tools_used=sorted({s.tool for s in steps}), injection_flags=sum(1 for s in steps if s.injection),
            step_errors=sum(1 for s in steps if not s.ok),
        )
        checks: list[dict] = []
        _check(checks, "run finished", run.status in ("done", "stopped_limit"), run.status)
        applied = [p for p in props if p.status == "applied"]
        _check(checks, "every applied line has evidence", all(p.evidence for p in applied), f"{len(applied)} applied")
        _check(checks, "applied candidate rates are real records", all(p.kind != "candidate" or (p.candidate_ref and p.apply.get("apply")) for p in applied))
        _check(checks, "step limit respected", all(s.steps <= max_steps for s in secs), f"max {max_steps}")
        _check(checks, "cost limit respected (one step of overshoot allowed)", float(run.cost_usd) <= budget * 1.5 + 1e-9, f"{float(run.cost_usd):.4f} of {budget}")
        _check(checks, "page-view limit respected", run.page_views <= (run.limits or {}).get("max_page_views", 60))
        _check(checks, "coverage reported for every finished section", all(s.coverage for s in secs if s.status in ("done", "stopped_limit")))
        from app.models.settlement import BidSettlementLineItem

        agent_lines = list(
            (await session.execute(select(BidSettlementLineItem).where(BidSettlementLineItem.agent_proposal_id.in_([p.id for p in applied] or [uuid.UUID(int=0)])))).scalars()
        )
        _check(checks, "no agent line is confirmed by the agent", all(l.agent_confirmed_by is None for l in agent_lines), f"{len(agent_lines)} agent lines")
        out["checks"] = checks
    return out


def render_markdown(r: dict) -> str:
    lines = [f"# Agent {('smoke' if r['provider'] != 'mock' else 'eval')}: {r['project']} ({r['provider']})", ""]
    lines += [f"- run `{r['run_id']}`: **{r['status']}** in {r['seconds']} s, {r['steps']} steps, {r['page_views']} page views, cost {r['cost_usd']:.4f} USD"]
    lines += [f"- files read {r['summary'].get('files_read')} of {r['files_in_pack']} in the pack (ratio {r['summary'].get('files_read_ratio')})"]
    lines += [f"- proposals {r['proposals']}, applied to the draft {r['applied']}; lines without a proposal {r['summary'].get('lines_without_proposal')}"]
    lines += [f"- cost per step {r['cost_per_step_usd']} USD; per section: " + ", ".join(f"{k}: {v:.4f}" for k, v in r["cost_by_section"].items())]
    lines += [f"- tools used: {', '.join(r['tools_used'])}; step errors {r['step_errors']}; injection-flagged results {r['injection_flags']}", "", "| check | ok | detail |", "|---|---|---|"]
    lines += [f"| {c['check']} | {'yes' if c['ok'] else '**NO**'} | {c['detail']} |" for c in r["checks"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--provider", choices=["mock", "configured"], default="mock")
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--confirm", action="store_true", help="accept the cost estimate of an external provider")
    ap.add_argument("--new-draft", action="store_true", help="start a new draft when the current settlement is already submitted")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = asyncio.run(run_eval(args.project, args.provider, args.budget, args.max_steps, args.confirm, args.new_draft))
    args.out.mkdir(parents=True, exist_ok=True)
    tag = "eval" if args.provider == "mock" else "smoke"
    (args.out / f"agent-{tag}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (args.out / f"agent-{tag}.md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    return 0 if all(c["ok"] for c in result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
