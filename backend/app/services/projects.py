from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction, Role
from app.core.errors import ForbiddenError, NotFoundError
from app.models.tenancy import Project, ProjectMember
from app.schemas.projects import ProjectCreate, ProjectLocationUpdate
from app.services import audit

# Mirrors app_can_see_project()'s role list (app/db/ddl.py) exactly --
# these three roles see every project regardless of project_members.
_PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES = frozenset(
    {Role.MANAGING_DIRECTOR.value, Role.BD_DIRECTOR.value, Role.PROCUREMENT_HEAD.value}
)


async def create_project(session: AsyncSession, ctx: RequestContext, data: ProjectCreate) -> Project:
    project = Project(
        tenant_id=ctx.tenant_id,
        code=data.code,
        name=data.name,
        client_name=data.client_name,
        tender_ref=data.tender_ref,
        base_currency=data.base_currency,
    )
    session.add(project)
    await session.flush()
    if ctx.user_id is not None:
        session.add(
            ProjectMember(project_id=project.id, user_id=ctx.user_id, tenant_id=ctx.tenant_id, project_role="owner")
        )
    await audit.record(
        session, ctx, action=AuditAction.CREATE, entity_type="project", entity_id=project.id,
        project_id=project.id, payload={"code": data.code},
    )
    return project


async def get_project(session: AsyncSession, project_id: UUID) -> Project:
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    return list((await session.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all())


async def assert_can_see_project(session: AsyncSession, ctx: RequestContext, project_id: UUID) -> None:
    """Application-side mirror of app_can_see_project() (app/db/ddl.py),
    for the narrow case of a *first* project-scoped write with no prior
    RLS-filtered read to naturally gate it first (e.g. uploading a new
    drawing -- unlike updating one already fetched via a project_scoped
    SELECT, whose own RLS policy already filtered out anything the caller
    can't see, an INSERT's WITH CHECK is the first thing that can fail,
    and it fails hard rather than silently returning nothing).

    Call this before any such write so an unauthorized caller gets a clean
    403 immediately -- before any side effect (e.g. streaming a file to
    S3) rather than letting Postgres's ProgrammingError('row-level
    security') surface as an unhandled 500 partway through.
    """
    if ctx.is_system or (ctx.roles & _PROJECT_VISIBLE_WITHOUT_MEMBERSHIP_ROLES):
        return
    if ctx.user_id is not None:
        result = await session.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == ctx.user_id
            )
        )
        if result.scalar_one_or_none() is not None:
            return
    raise ForbiddenError(f"Not a member of project {project_id}")


async def update_location(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, data: ProjectLocationUpdate
) -> Project:
    """Module C Phase 6: feeds app.services.procurement::
    _vendor_geography_eligible's project side. Nullable fields are set
    exactly as given, including explicitly clearing one back to NULL (a
    plain PATCH-with-omitted-field semantic isn't used here -- every field
    on ProjectLocationUpdate is always applied, matching how
    replace_pdf_layer_mapping_rules-style whole-value config updates work
    elsewhere in this codebase, not a partial merge)."""
    project = await get_project(session, project_id)
    project.emirate = data.emirate
    project.area = data.area
    project.latitude = data.latitude
    project.longitude = data.longitude
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project", entity_id=project_id,
        project_id=project_id, payload={"emirate": data.emirate, "area": data.area},
    )
    return project


async def add_member(session: AsyncSession, ctx: RequestContext, project_id: UUID, user_id: UUID, role: str | None) -> None:
    await get_project(session, project_id)  # 404s if missing / not visible under RLS
    session.add(ProjectMember(project_id=project_id, user_id=user_id, tenant_id=ctx.tenant_id, project_role=role))
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project", entity_id=project_id,
        project_id=project_id, payload={"member_added": str(user_id), "role": role},
    )
