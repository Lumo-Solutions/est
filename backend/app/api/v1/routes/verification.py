from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import AuditAction, Role
from app.core.errors import ConflictError
from app.models.tenancy import Project
from app.schemas.verification import (
    EvidenceOut,
    EvidenceSearchOut,
    MappingIn,
    MappingOut,
    VerificationLineOut,
    VerificationLinePage,
    VerificationRunCreate,
    VerificationRunOut,
)
from app.services import audit
from app.services import verification as svc
from app.verification import export as vexport

router = APIRouter(tags=["verification"])

# Starting a run spends AI budget: lead_estimator and above. Working the report (accept / override
# a mapping) is ordinary estimating work: any estimator on the project.
_RUN_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_WORK_ROLES = (Role.ESTIMATOR.value, *_RUN_ROLES)


def _dispatch(ctx: RequestContext, run_id: UUID) -> None:
    from app.workers.tasks.ai_reading import run_verification

    run_verification.apply_async(
        args=(str(run_id), str(ctx.tenant_id), str(ctx.user_id) if ctx.user_id else None, list(ctx.roles)), countdown=2
    )


@router.post("/projects/{project_id}/verification-runs", response_model=VerificationRunOut, status_code=202)
async def create_run_endpoint(
    project_id: UUID,
    body: VerificationRunCreate | None = None,
    ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> VerificationRunOut:
    run = await svc.create_run(session, ctx, project_id, use_ai=(body.use_ai if body else True))
    _dispatch(ctx, run.id)
    return VerificationRunOut.model_validate(run)


@router.get("/projects/{project_id}/verification-runs", response_model=list[VerificationRunOut])
async def list_runs_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[VerificationRunOut]:
    return [VerificationRunOut.model_validate(r) for r in await svc.list_runs(session, project_id)]


@router.get("/verification-runs/{run_id}", response_model=VerificationRunOut)
async def get_run_endpoint(
    run_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> VerificationRunOut:
    return VerificationRunOut.model_validate(await svc.get_run(session, run_id))


@router.post("/verification-runs/{run_id}/retry", response_model=VerificationRunOut, status_code=202)
async def retry_run_endpoint(
    run_id: UUID, ctx: RequestContext = Depends(require_roles(*_RUN_ROLES)), session: AsyncSession = Depends(get_session)
) -> VerificationRunOut:
    run = await svc.get_run(session, run_id)
    if run.status != "failed":
        raise ConflictError(f"Only a failed run can be retried (this one is {run.status})")
    run.status, run.error, run.progress_done = "queued", None, 0
    await session.flush()
    _dispatch(ctx, run.id)
    return VerificationRunOut.model_validate(run)


@router.get("/verification-runs/{run_id}/lines", response_model=VerificationLinePage)
async def list_lines_endpoint(
    run_id: UUID,
    vclass: str | None = None,
    trade: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> VerificationLinePage:
    rows, total = await svc.list_lines(
        session, run_id, vclass=vclass, trade=trade, min_confidence=min_confidence, max_confidence=max_confidence,
        q=q, limit=limit, offset=offset,
    )
    return VerificationLinePage(items=[VerificationLineOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/verification-runs/{run_id}/lines/{line_id}", response_model=VerificationLineOut)
async def get_line_endpoint(
    run_id: UUID, line_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> VerificationLineOut:
    return VerificationLineOut.model_validate(await svc.get_line(session, run_id, line_id))


@router.post("/verification-runs/{run_id}/lines/{line_id}/mapping", response_model=MappingOut)
async def set_mapping_endpoint(
    run_id: UUID,
    line_id: UUID,
    body: MappingIn,
    ctx: RequestContext = Depends(require_roles(*_WORK_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> MappingOut:
    line = await svc.set_mapping(session, ctx, run_id, line_id, action=body.action, evidence_ref=body.evidence_ref, note=body.note)
    run = await svc.get_run(session, run_id)
    return MappingOut(line=VerificationLineOut.model_validate(line), run=VerificationRunOut.model_validate(run))


@router.get("/projects/{project_id}/verification-evidence", response_model=EvidenceSearchOut)
async def evidence_search_endpoint(
    project_id: UUID,
    q: str | None = Query(default=None, max_length=100),
    kind: str | None = Query(default=None, pattern="^(measurement|annotation)$"),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> EvidenceSearchOut:
    found = await svc.search_evidence(session, project_id, q=q, kind=kind, limit=limit)
    return EvidenceSearchOut(items=[EvidenceOut(**svc._ev_json(e)) for e in found])


async def _export(run_id: UUID, ctx: RequestContext, session: AsyncSession, fmt: str) -> Response:
    run = await svc.get_run(session, run_id)
    project = (await session.execute(select(Project).where(Project.id == run.project_id))).scalar_one()
    lines = await svc.all_lines(session, run_id)
    label = f"{project.code} {project.name}"
    if fmt == "xlsx":
        data, media = vexport.build_xlsx(run, lines, label), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data, media = vexport.build_pdf(run, lines, label), "application/pdf"
    await audit.record(
        session, ctx, action=AuditAction.EXPORT, entity_type="verification_run", entity_id=run.id, project_id=run.project_id,
        payload={"format": fmt, "lines": len(lines)},
    )
    name = f"verification-{project.code}.{fmt}".replace(" ", "_")
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/verification-runs/{run_id}/export.xlsx")
async def export_xlsx_endpoint(
    run_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> Response:
    return await _export(run_id, ctx, session, "xlsx")


@router.get("/verification-runs/{run_id}/export.pdf")
async def export_pdf_endpoint(
    run_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> Response:
    return await _export(run_id, ctx, session, "pdf")
