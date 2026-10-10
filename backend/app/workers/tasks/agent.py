"""BOQ agent Celery tasks (queue `agent`, concurrency 1 on dev; docs/boq-agent/plan.md section 3.5).

* ``agent_plan_run``: writes the plan, then starts the first section.
* ``agent_run_section``: claims the next pending section of a run, runs its loop, applies the proposals to the draft
  settlement as the person who started the run, then queues the next section. Pause, resume and cancel are seen between steps.
* ``agent_chat_turn``: one chat message = one short run with the chat limits.
* ``agent_tick`` (beat, every minute): sections left `reading` by a dead worker go back to `pending` once, then fail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update

from app.agent import chat as agent_chat
from app.agent import runner
from app.core.context import system_context
from app.db.session import worker_session_scope
from app.models.agent import AgentRun, AgentRunSection
from app.workers.base import run_async
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
STUCK_AFTER = timedelta(minutes=35)


def enqueue(kind: str, run_id: UUID, tenant_id: UUID, countdown: int = 1) -> None:
    """What happens next, as a Celery message. `kind`: plan | section | chat."""
    task = {"plan": agent_plan_run, "section": agent_run_section, "chat": agent_chat_turn}[kind]
    task.apply_async(args=(str(run_id), str(tenant_id)), countdown=countdown)


@celery_app.task(name="app.workers.tasks.agent.agent_plan_run", acks_late=True)
def agent_plan_run(run_id: str, tenant_id: str) -> None:
    run_async(lambda: runner.plan_run(UUID(run_id), UUID(tenant_id), enqueue))()


@celery_app.task(name="app.workers.tasks.agent.agent_run_section", acks_late=True)
def agent_run_section(run_id: str, tenant_id: str) -> None:
    run_async(lambda: runner.run_next_section(UUID(run_id), UUID(tenant_id), enqueue))()


@celery_app.task(name="app.workers.tasks.agent.agent_chat_turn", acks_late=True)
def agent_chat_turn(run_id: str, tenant_id: str) -> None:
    run_async(lambda: agent_chat.run_turn(UUID(run_id), UUID(tenant_id), enqueue))()


async def _tick() -> dict[str, int]:
    from app.models.tenancy import Tenant

    out = {"requeued": 0, "failed": 0}
    cutoff = datetime.now(timezone.utc) - STUCK_AFTER
    nil = system_context(UUID(int=0))
    async with worker_session_scope(nil) as session:
        tenants = [r[0] for r in (await session.execute(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()]
    for tenant_id in tenants:
        ctx = system_context(tenant_id)
        async with worker_session_scope(ctx) as session:
            stuck = list(
                (
                    await session.execute(
                        select(AgentRunSection).where(AgentRunSection.status == "reading", AgentRunSection.updated_at < cutoff)
                    )
                ).scalars()
            )
            runs: set[UUID] = set()
            for s in stuck:
                # One more try from the start of the section; the steps already recorded stay in the trace.
                if (s.error or "") == "restarted_after_stall":
                    s.status, s.error = "failed", "The worker stopped answering twice in this section."
                    out["failed"] += 1
                else:
                    s.status, s.error = "pending", "restarted_after_stall"
                    out["requeued"] += 1
                runs.add(s.run_id)
            for rid in runs:
                run = (await session.execute(select(AgentRun).where(AgentRun.id == rid))).scalar_one()
                if run.status == "running":
                    enqueue("section", rid, tenant_id)
    return out


@celery_app.task(name="app.workers.tasks.agent.agent_tick")
def agent_tick() -> dict[str, int]:
    return run_async(_tick)()
