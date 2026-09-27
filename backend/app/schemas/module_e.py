from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from app.schemas.common import JsonDecimal, ORMModel


class ContractOut(ORMModel):
    id: UUID
    project_id: UUID
    settlement_id: UUID
    contract_ref: str | None
    status: str
    awarded_at: datetime | None
    created_at: datetime


class BoqRevisionOut(ORMModel):
    id: UUID
    project_id: UUID
    revision_no: int
    parent_revision_id: UUID | None
    import_batch_id: UUID | None
    reason: str | None
    created_at: datetime


class ContractRevisionOut(ORMModel):
    id: UUID
    project_id: UUID
    contract_id: UUID
    revision_no: int
    parent_revision_id: UUID | None
    reason: str | None
    created_at: datetime


class ContractVariationOut(ORMModel):
    id: UUID
    project_id: UUID
    contract_id: UUID
    revision_id: UUID
    variation_ref: str | None
    description: str
    delta_amount: JsonDecimal | None
    status: str
    created_at: datetime


class ExclusionRegisterEntryOut(ORMModel):
    id: UUID
    project_id: UUID
    contract_id: UUID | None
    source_exclusion_flag_id: UUID | None
    description: str
    status: str
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime


class OutturnCostObservationOut(ORMModel):
    id: UUID
    project_id: UUID
    contract_id: UUID
    boq_line_item_id: UUID | None
    cost_item_id: UUID | None
    observed_unit_cost: JsonDecimal
    observed_quantity: JsonDecimal | None
    currency: str
    observed_at: date
    source_note: str | None
    written_back_rate_id: UUID | None
    created_at: datetime
