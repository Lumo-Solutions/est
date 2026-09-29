from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.common import Page
from app.schemas.projects import (
    ProjectCreate,
    ProjectLocationUpdate,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectOut,
)
from app.services import projects as projects_service

router = APIRouter(prefix="/projects", tags=["projects"])

_CREATE_ROLES = (Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)

# Mirrors app/services/{vendors,costlib}.py's list endpoints' page size.
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 200


@router.get("", response_model=list[ProjectOut] | Page)
async def list_projects_endpoint(
    limit: int | None = Query(default=None, ge=1, le=_MAX_PAGE_SIZE),
    offset: int | None = Query(default=None, ge=0),
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[ProjectOut] | Page:
    """Backward compatibility: called with NEITHER `limit` nor `offset` --
    as LayerTradeMappingAdmin.tsx and TolerancesAdmin.tsx's project-picker
    dropdowns do via useProjects() -- this returns the exact same bare,
    unbounded `list[ProjectOut]` JSON array it always has. Passing either
    `limit` or `offset` (as ProjectsListPage's useProjectsPage() does)
    switches to the paginated shape, mirroring GET /vendors and
    GET /cost-items: a `Page` envelope ({items, total, limit, offset}),
    same created_at-desc ordering as the unpaginated list."""
    if limit is None and offset is None:
        return [ProjectOut.model_validate(p) for p in await projects_service.list_projects(session)]
    effective_limit = limit if limit is not None else _DEFAULT_PAGE_SIZE
    effective_offset = offset if offset is not None else 0
    projects, total = await projects_service.list_projects_page(
        session, limit=effective_limit, offset=effective_offset
    )
    return Page(
        items=[ProjectOut.model_validate(p) for p in projects],
        total=total,
        limit=effective_limit,
        offset=effective_offset,
    )


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project_endpoint(
    data: ProjectCreate,
    ctx: RequestContext = Depends(require_roles(*_CREATE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await projects_service.create_project(session, ctx, data)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> ProjectOut:
    return ProjectOut.model_validate(await projects_service.get_project(session, project_id))


@router.patch("/{project_id}/location", response_model=ProjectOut)
async def update_project_location_endpoint(
    project_id: UUID,
    data: ProjectLocationUpdate,
    ctx: RequestContext = Depends(require_roles(*_CREATE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await projects_service.update_location(session, ctx, project_id, data)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
async def list_members_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ProjectMemberOut]:
    return [ProjectMemberOut.model_validate(m) for m in await projects_service.list_members(session, project_id)]


@router.post("/{project_id}/members", status_code=204, response_model=None)
async def add_member_endpoint(
    project_id: UUID,
    data: ProjectMemberAdd,
    ctx: RequestContext = Depends(require_roles(*_CREATE_ROLES, Role.LEAD_ESTIMATOR.value)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await projects_service.add_member(session, ctx, project_id, data.user_id, data.project_role)


@router.delete("/{project_id}/members/{user_id}", status_code=204, response_model=None)
async def remove_member_endpoint(
    project_id: UUID,
    user_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_CREATE_ROLES, Role.LEAD_ESTIMATOR.value)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await projects_service.remove_member(session, ctx, project_id, user_id)
