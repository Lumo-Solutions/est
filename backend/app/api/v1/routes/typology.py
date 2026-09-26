from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.typology import (
    ConfirmClusterRequest,
    TypologyClusterInstanceOut,
    TypologyClusterOut,
    TypologyRollupOut,
    TypologyVariantDeltaOut,
)
from app.services import typology as typology_service

router = APIRouter(tags=["typology"])

# Detecting/confirming/rejecting clusters is structural, project-level
# configuration work -- same tier as boq_tolerances/drawing_layer_trade_
# mappings, matching migration 0024's own WRITE_ROLES.
_STRUCTURE_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.MANAGING_DIRECTOR.value)


@router.post("/projects/{project_id}/typology-clusters/detect", response_model=list[TypologyClusterOut])
async def detect_typology_clusters_endpoint(
    project_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[TypologyClusterOut]:
    clusters = await typology_service.detect_clusters(session, ctx, project_id)
    return [TypologyClusterOut.model_validate(c) for c in clusters]


@router.get("/projects/{project_id}/typology-clusters", response_model=list[TypologyClusterOut])
async def list_typology_clusters_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[TypologyClusterOut]:
    clusters = await typology_service.list_clusters(session, project_id)
    return [TypologyClusterOut.model_validate(c) for c in clusters]


@router.get("/typology-clusters/{cluster_id}", response_model=TypologyClusterOut)
async def get_typology_cluster_endpoint(
    cluster_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> TypologyClusterOut:
    cluster = await typology_service.get_cluster(session, cluster_id)
    return TypologyClusterOut.model_validate(cluster)


@router.get("/typology-clusters/{cluster_id}/instances", response_model=list[TypologyClusterInstanceOut])
async def list_typology_cluster_instances_endpoint(
    cluster_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[TypologyClusterInstanceOut]:
    instances = await typology_service.list_cluster_instances(session, cluster_id)
    return [TypologyClusterInstanceOut.model_validate(i) for i in instances]


@router.get("/typology-clusters/{cluster_id}/deltas", response_model=list[TypologyVariantDeltaOut])
async def list_typology_variant_deltas_endpoint(
    cluster_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[TypologyVariantDeltaOut]:
    deltas = await typology_service.list_variant_deltas(session, cluster_id)
    return [TypologyVariantDeltaOut.model_validate(d) for d in deltas]


@router.post("/typology-clusters/{cluster_id}/confirm", response_model=TypologyClusterOut)
async def confirm_typology_cluster_endpoint(
    cluster_id: UUID,
    data: ConfirmClusterRequest,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TypologyClusterOut:
    cluster = await typology_service.confirm_cluster(
        session, ctx, cluster_id,
        groups=[g.model_dump() for g in data.groups], master_group_label=data.master_group_label,
        deltas=[d.model_dump() for d in data.deltas],
    )
    return TypologyClusterOut.model_validate(cluster)


@router.post("/typology-clusters/{cluster_id}/reject", response_model=TypologyClusterOut)
async def reject_typology_cluster_endpoint(
    cluster_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_STRUCTURE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TypologyClusterOut:
    cluster = await typology_service.reject_cluster(session, ctx, cluster_id)
    return TypologyClusterOut.model_validate(cluster)


@router.get("/typology-clusters/{cluster_id}/rollup", response_model=TypologyRollupOut)
async def get_typology_cluster_rollup_endpoint(
    cluster_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> TypologyRollupOut:
    rollup = await typology_service.get_rollup(session, cluster_id)
    return TypologyRollupOut.model_validate(rollup)
