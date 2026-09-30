from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.ai import (
    AiSettingsIn,
    AiSettingsOut,
    AiStatusOut,
    AiUsageOut,
    ProjectAiOverrideIn,
    ProjectAiOverrideOut,
)
from app.services import ai_admin

router = APIRouter(tags=["ai"])

# Only the managing director turns external AI on or off (tenant data leaves
# the boundary). Keeping one project off it is a confidentiality call for
# bd_director/managing_director, matching who may edit a project (RLS).
_SWITCH_ROLES = (Role.MANAGING_DIRECTOR.value,)
_PROJECT_ROLES = (Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_USAGE_ROLES = (Role.MANAGING_DIRECTOR.value, Role.BD_DIRECTOR.value)


@router.get("/ai/status", response_model=AiStatusOut)
async def ai_status_endpoint(
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiStatusOut:
    return await ai_admin.get_status(session, ctx, settings)


@router.put("/admin/ai-settings", response_model=AiSettingsOut)
async def set_ai_settings_endpoint(
    body: AiSettingsIn,
    ctx: RequestContext = Depends(require_roles(*_SWITCH_ROLES)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiSettingsOut:
    return await ai_admin.set_external_allowed(session, ctx, settings, body.external_ai_allowed)


@router.put("/projects/{project_id}/ai-override", response_model=ProjectAiOverrideOut)
async def set_project_ai_override_endpoint(
    project_id: UUID,
    body: ProjectAiOverrideIn,
    ctx: RequestContext = Depends(require_roles(*_PROJECT_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> ProjectAiOverrideOut:
    return await ai_admin.set_project_override(session, ctx, project_id, body.external_ai_override)


@router.get("/admin/ai-usage", response_model=AiUsageOut)
async def ai_usage_endpoint(
    days: int = Query(default=30, ge=1, le=366),
    ctx: RequestContext = Depends(require_roles(*_USAGE_ROLES)),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiUsageOut:
    return await ai_admin.usage(session, ctx, settings, days=days)
