"""Chat: one user message is one short agent turn with the same tools and the chat limits (docs/boq-agent/plan.md section 3.6).

A turn can look things up, explain a line, propose lines (through `propose_line` and the same applier as a run) and ask for a
section re-run. It cannot submit, approve, or change percentages, FX rates or quantities: those tools do not exist.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.agent import applier, runner
from app.agent.loop import SectionOutcome, SectionRuntime, run_section
from app.core.config import get_settings
from app.core.context import system_context
from app.db.session import worker_session_scope
from app.models.agent import AgentMessage, AgentRun

logger = logging.getLogger(__name__)
HISTORY_MESSAGES = 6
REPLY_LIMIT = 4000

Enqueue = Callable[[str, UUID, UUID], None]


async def run_turn(run_id: UUID, tenant_id: UUID, enqueue: Enqueue) -> None:
    settings = get_settings()
    ctx = system_context(tenant_id)
    async with worker_session_scope(ctx) as session:
        run = (await session.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        if run.kind != "chat" or run.status not in ("queued", "running"):
            return
        run.status, run.started_at = "running", datetime.now(timezone.utc)
        msgs = list(
            (
                await session.execute(
                    select(AgentMessage).where(AgentMessage.conversation_id == run.conversation_id).order_by(AgentMessage.created_at.desc()).limit(HISTORY_MESSAGES)
                )
            ).scalars()
        )[::-1]
        project_id, settlement_id, conversation_id = run.project_id, run.settlement_id, run.conversation_id
        started_by, roles = run.started_by, list(run.started_by_roles or [])
        limits = runner.limits_of(run, chat=True)
    last_user = next((m.content for m in reversed(msgs) if m.role == "user"), "")
    history = "\n".join(f"{m.role}: {m.content[:400]}" for m in msgs[:-1])
    rt = SectionRuntime(
        ctx=ctx, run_id=run_id, section_id=None, project_id=project_id, settlement_id=settlement_id, label="Chat with the estimator",
        item_no="chat", line_ids=[], line_brief={}, plan=None, user_note=(f"Earlier in this chat:\n{history}" if history else None),
        limits=limits, settings=settings, gateway=runner._gateway(), chat_prompt=last_user[:1500],
    )
    try:
        outcome = await run_section(rt)
    except Exception as exc:  # noqa: BLE001 -- the user gets a message, not a stuck spinner
        logger.exception("agent chat: turn %s failed", run_id)
        outcome = SectionOutcome("failed", error=f"{type(exc).__name__}")
    reply = _reply(outcome)
    rerun_note = await _start_requested_reruns(ctx, tenant_id, run_id, started_by, roles, project_id, rt, enqueue)
    if rerun_note:
        reply = f"{reply}\n\n{rerun_note}".strip()
    status = {"done": "done", "stopped_limit": "stopped_limit"}.get(outcome.status, outcome.status)
    if rt.state.proposed:
        user_ctx = applier.user_context(tenant_id, started_by, roles)
        try:
            async with worker_session_scope(user_ctx) as session:
                result = await applier.apply_proposals(session, user_ctx, project_id, run_id)
            if result.applied:
                reply += f"\n\n{result.applied} line(s) were added to the draft settlement. They need your confirmation before submit."
            elif result.reason:
                reply += f"\n\nThe proposals were not applied ({result.reason.replace('_', ' ')})."
        except Exception:  # noqa: BLE001
            logger.exception("agent chat: apply failed")
    async with worker_session_scope(ctx) as session:
        run = (await session.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
        run.status, run.finished_at, run.error = status, datetime.now(timezone.utc), outcome.error
        session.add(
            AgentMessage(tenant_id=tenant_id, project_id=project_id, conversation_id=conversation_id, role="assistant", content=reply[:REPLY_LIMIT], run_id=run_id,
                         created_at=datetime.now(timezone.utc))
        )


def _reply(outcome: SectionOutcome) -> str:
    if outcome.status == "done" and outcome.summary:
        return outcome.summary
    if outcome.status == "stopped_limit":
        return f"I stopped before finishing: {outcome.summary or 'the limit for one chat turn was reached'}. Ask me to continue, or narrow the question."
    if outcome.status == "blocked":
        return f"I cannot answer right now: {outcome.error or 'the AI is not available for this project'}."
    if outcome.status == "cancelled":
        return "This turn was cancelled."
    return f"I could not finish that: {outcome.error or 'something went wrong'}."


async def _start_requested_reruns(ctx, tenant_id, chat_run_id, started_by, roles, project_id, rt: SectionRuntime, enqueue: Enqueue) -> str | None:
    """`rerun_section` only validates; the turn starts the re-run itself, as the person who is chatting."""
    from app.services import agent as agent_service

    asks = [
        w["result"]["request_rerun"]
        for w in rt.window
        if w.get("tool") == "rerun_section" and w.get("ok") and isinstance(w.get("result"), dict) and "request_rerun" in w["result"]
    ]
    if not asks:
        return None
    user_ctx = applier.user_context(tenant_id, started_by, roles)
    notes = []
    for ask in asks[:1]:
        try:
            async with worker_session_scope(user_ctx) as session:
                new = await agent_service.create_run(
                    session, user_ctx, project_id, sections=[ask["section_item_id"]], notes={ask["section_item_id"]: ask["note"]}, enqueue=enqueue,
                    from_chat=True,
                )
                status, label = new.status, ask["label"]
            notes.append(
                f"I started a re-run of {label} with your note."
                if status != "awaiting_confirm"
                else f"A re-run of {label} is ready but needs you to confirm its cost estimate on the Agent tab."
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"I could not start the re-run: {str(exc)[:160]}")
    return " ".join(notes)
