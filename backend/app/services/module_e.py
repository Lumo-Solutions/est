"""Module E Phase 1: read-only access to the schema-readiness tables --
contracts, BOQ/contract revisions, the live exclusion register, and
outturn cost observations. No create/update functions here -- this phase
is schema and RLS only, no workflow; rows are seeded directly (by a later
phase's real workflow, or a dev-sim/test script talking straight to the
ORM). See docs/module-e-schema-design.md."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.module_e import (
    BoqRevision,
    Contract,
    ContractRevision,
    ContractVariation,
    ExclusionRegisterEntry,
    OutturnCostObservation,
)


async def list_contracts(session: AsyncSession, project_id: UUID) -> list[Contract]:
    result = await session.execute(select(Contract).where(Contract.project_id == project_id).order_by(Contract.created_at))
    return list(result.scalars().all())


async def get_contract(session: AsyncSession, contract_id: UUID) -> Contract:
    result = await session.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if contract is None:
        raise NotFoundError(f"Contract {contract_id} not found")
    return contract


async def list_contract_revisions(session: AsyncSession, contract_id: UUID) -> list[ContractRevision]:
    result = await session.execute(
        select(ContractRevision).where(ContractRevision.contract_id == contract_id).order_by(ContractRevision.revision_no)
    )
    return list(result.scalars().all())


async def list_contract_variations(session: AsyncSession, contract_id: UUID) -> list[ContractVariation]:
    result = await session.execute(
        select(ContractVariation).where(ContractVariation.contract_id == contract_id).order_by(ContractVariation.created_at)
    )
    return list(result.scalars().all())


async def list_boq_revisions(session: AsyncSession, project_id: UUID) -> list[BoqRevision]:
    result = await session.execute(
        select(BoqRevision).where(BoqRevision.project_id == project_id).order_by(BoqRevision.revision_no)
    )
    return list(result.scalars().all())


async def list_exclusion_register(session: AsyncSession, project_id: UUID, *, status: str | None = None) -> list[ExclusionRegisterEntry]:
    stmt = select(ExclusionRegisterEntry).where(ExclusionRegisterEntry.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ExclusionRegisterEntry.status == status)
    result = await session.execute(stmt.order_by(ExclusionRegisterEntry.created_at))
    return list(result.scalars().all())


async def list_outturn_cost_observations(session: AsyncSession, project_id: UUID) -> list[OutturnCostObservation]:
    result = await session.execute(
        select(OutturnCostObservation).where(OutturnCostObservation.project_id == project_id).order_by(OutturnCostObservation.observed_at)
    )
    return list(result.scalars().all())
