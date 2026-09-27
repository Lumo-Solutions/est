from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

PctType = Literal["plant", "overhead", "volatility", "markup"]


class TradeOverrideUpdate(BaseModel):
    """PUT-with-patch-semantics: only fields present in the request body are
    touched (see app/services/settlement.py's use of model_fields_set). A
    field explicitly set to null clears that override (reverts to the
    project default); a field simply absent from the JSON body leaves
    whatever override already exists untouched."""

    plant_pct: float | None = None
    overhead_pct: float | None = None
    volatility_pct: float | None = None
    markup_pct: float | None = None


class BidSettlementTradeOverrideOut(ORMModel):
    id: UUID
    trade_node_id: UUID
    plant_pct: Decimal | None
    overhead_pct: Decimal | None
    volatility_pct: Decimal | None
    markup_pct: Decimal | None


class SettlementDefaultsUpdate(BaseModel):
    currency: str | None = None
    default_plant_pct: float | None = None
    default_overhead_pct: float | None = None
    default_volatility_pct: float | None = None
    default_markup_pct: float | None = None


class LineCostUpdate(BaseModel):
    """Exactly one cost_source-shaped set of fields is used, chosen by
    cost_source; see app/services/settlement.py::set_line_cost for the
    validation. Percentage override fields follow the same exclude-unset
    "only touch what's present" rule as TradeOverrideUpdate."""

    cost_source: Literal["quotation_line", "cost_library_rate", "manual"] | None = None
    source_quotation_line_item_id: UUID | None = None
    cost_item_id: UUID | None = None
    valid_on: date | None = None
    manual_unit_cost: Decimal | None = None
    manual_currency: str | None = None
    source_note: str | None = None

    plant_pct_override: float | None = None
    overhead_pct_override: float | None = None
    volatility_pct_override: float | None = None
    markup_pct_override: float | None = None
    line_note: str | None = None


class FxRateSet(BaseModel):
    fx_rate: Decimal = Field(gt=0)
    fx_rate_date: date


class BidSettlementLineItemOut(ORMModel):
    id: UUID
    boq_line_item_id: UUID
    quantity: Decimal
    quantity_at_build: Decimal
    direct_unit_cost: Decimal | None
    source_currency: str
    cost_source: str
    source_quotation_line_item_id: UUID | None
    source_cost_item_rate_id: UUID | None
    source_rate_as_of_date: date | None
    source_set_by: UUID | None
    source_set_at: datetime | None
    source_note: str | None
    fx_rate: Decimal | None
    fx_rate_date: date | None
    plant_pct_override: Decimal | None
    overhead_pct_override: Decimal | None
    volatility_pct_override: Decimal | None
    markup_pct_override: Decimal | None
    unit_sell_rate: Decimal | None
    line_amount: Decimal | None
    line_note: str | None


class BidSettlementOut(ORMModel):
    id: UUID
    project_id: UUID
    version_no: int
    is_current: bool
    status: str
    currency: str
    default_plant_pct: Decimal
    default_overhead_pct: Decimal
    default_volatility_pct: Decimal
    default_markup_pct: Decimal
    direct_cost_total: Decimal | None
    plant_total: Decimal | None
    overhead_total: Decimal | None
    volatility_total: Decimal | None
    markup_total: Decimal | None
    tender_total: Decimal | None
    rounding_difference: Decimal | None
    margin_on_sell_pct: Decimal | None
    approval_request_id: UUID | None
    quantities_refreshed_at: datetime | None
    submitted_at: datetime | None
    submitted_by: UUID | None
    decided_at: datetime | None
    decided_by: UUID | None
    outcome: str | None
    outcome_our_price: Decimal | None
    outcome_winning_price: Decimal | None
    outcome_competitor_names: list[str]
    outcome_competitor_vendor_ids: list[UUID]
    outcome_reason_codes: list[str]
    outcome_recorded_by: UUID | None
    outcome_recorded_at: datetime | None
    outcome_note: str | None
    notes: str | None
    lines: list[BidSettlementLineItemOut] = []
    trade_overrides: list[BidSettlementTradeOverrideOut] = []


class QuantityMismatch(ORMModel):
    boq_line_item_id: UUID
    settlement_quantity: Decimal
    current_boq_quantity: Decimal


# --------------------------------------------------------------------------
# simulate() -- stateless, no DB writes
# --------------------------------------------------------------------------


class SimulateLineOverride(BaseModel):
    plant_pct: float | None = None
    overhead_pct: float | None = None
    volatility_pct: float | None = None
    markup_pct: float | None = None


class SimulateRequest(BaseModel):
    """Every field is optional and defaults to the settlement's own stored
    values -- passing nothing simulates the settlement exactly as it
    currently stands. Nothing here is ever persisted (see
    app/services/settlement.py::simulate)."""

    default_plant_pct: float | None = None
    default_overhead_pct: float | None = None
    default_volatility_pct: float | None = None
    default_markup_pct: float | None = None
    trade_overrides: dict[UUID, SimulateLineOverride] = Field(default_factory=dict)
    line_overrides: dict[UUID, SimulateLineOverride] = Field(default_factory=dict)


class SimulateLineResult(BaseModel):
    boq_line_item_id: UUID
    resolved: bool
    quantity: Decimal
    direct_unit_cost: Decimal | None
    plant_pct: Decimal
    overhead_pct: Decimal
    volatility_pct: Decimal
    markup_pct: Decimal
    base: Decimal
    plant: Decimal
    overhead: Decimal
    volatility: Decimal
    markup: Decimal
    model_sell: Decimal
    unit_sell_rate: Decimal | None
    line_amount: Decimal | None


class SimulateResult(BaseModel):
    lines: list[SimulateLineResult]
    unresolved_line_ids: list[UUID]
    direct_cost_total: Decimal
    plant_total: Decimal
    overhead_total: Decimal
    volatility_total: Decimal
    markup_total: Decimal
    exact_model_total: Decimal
    tender_total: Decimal
    rounding_difference: Decimal
    margin_on_sell_pct: Decimal | None
    required_role: str | None


class ScenarioCreate(BaseModel):
    label: str
    inputs: SimulateRequest


class BidSettlementScenarioOut(ORMModel):
    id: UUID
    label: str
    inputs: dict
    result: dict
    created_by: UUID | None
    created_at: datetime


# --------------------------------------------------------------------------
# Module D2: generated export, win/loss
# --------------------------------------------------------------------------


class ExportRequest(BaseModel):
    include_vat: bool = False
    vat_pct: float = 5.0


class OutcomeRequest(BaseModel):
    outcome: Literal["won", "lost"]
    our_price: Decimal | None = None
    winning_price: Decimal | None = None
    competitor_names: list[str] = Field(default_factory=list)
    competitor_vendor_ids: list[UUID] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    note: str | None = None


class SettlementReasonCodeOut(ORMModel):
    id: UUID
    code: str
    label: str
    is_active: bool


class ReasonCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=255)


class ReasonCodeUpdate(BaseModel):
    label: str | None = None
    is_active: bool | None = None


# --------------------------------------------------------------------------
# Module D3: export into the client's original workbook
# --------------------------------------------------------------------------


class OriginalExportRequest(BaseModel):
    accept_loss: bool = False


class FidelityReportOut(BaseModel):
    ok: bool
    lost_features: list[str] = Field(default_factory=list)
    unexpected_cell_changes: list[str] = Field(default_factory=list)
