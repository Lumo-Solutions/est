from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session
from app.core.context import RequestContext
from app.schemas.module_e import (
    BoqRevisionOut,
    ContractOut,
    ContractRevisionOut,
    ContractVariationOut,
    ExclusionRegisterEntryOut,
    OutturnCostObservationOut,
)
from app.services import module_e as module_e_service

router = APIRouter(tags=["module-e"])


@router.get("/projects/{project_id}/contracts", response_model=list[ContractOut])
async def list_contracts_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ContractOut]:
    rows = await module_e_service.list_contracts(session, project_id)
    return [ContractOut.model_validate(r) for r in rows]


@router.get("/contracts/{contract_id}", response_model=ContractOut)
async def get_contract_endpoint(
    contract_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> ContractOut:
    row = await module_e_service.get_contract(session, contract_id)
    return ContractOut.model_validate(row)


@router.get("/contracts/{contract_id}/revisions", response_model=list[ContractRevisionOut])
async def list_contract_revisions_endpoint(
    contract_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ContractRevisionOut]:
    rows = await module_e_service.list_contract_revisions(session, contract_id)
    return [ContractRevisionOut.model_validate(r) for r in rows]


@router.get("/contracts/{contract_id}/variations", response_model=list[ContractVariationOut])
async def list_contract_variations_endpoint(
    contract_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ContractVariationOut]:
    rows = await module_e_service.list_contract_variations(session, contract_id)
    return [ContractVariationOut.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/boq-revisions", response_model=list[BoqRevisionOut])
async def list_boq_revisions_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BoqRevisionOut]:
    rows = await module_e_service.list_boq_revisions(session, project_id)
    return [BoqRevisionOut.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/exclusion-register", response_model=list[ExclusionRegisterEntryOut])
async def list_exclusion_register_endpoint(
    project_id: UUID, status: str | None = None, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[ExclusionRegisterEntryOut]:
    rows = await module_e_service.list_exclusion_register(session, project_id, status=status)
    return [ExclusionRegisterEntryOut.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/outturn-cost-observations", response_model=list[OutturnCostObservationOut])
async def list_outturn_cost_observations_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[OutturnCostObservationOut]:
    rows = await module_e_service.list_outturn_cost_observations(session, project_id)
    return [OutturnCostObservationOut.model_validate(r) for r in rows]
