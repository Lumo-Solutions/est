from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import NotFoundError
from app.models.tenancy import Project, ProjectMember
from app.schemas.projects import ProjectCreate
from app.services import audit


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


async def add_member(session: AsyncSession, ctx: RequestContext, project_id: UUID, user_id: UUID, role: str | None) -> None:
    await get_project(session, project_id)  # 404s if missing / not visible under RLS
    session.add(ProjectMember(project_id=project_id, user_id=user_id, tenant_id=ctx.tenant_id, project_role=role))
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="project", entity_id=project_id,
        project_id=project_id, payload={"member_added": str(user_id), "role": role},
    )
