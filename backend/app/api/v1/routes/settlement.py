from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_session, require_roles
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.approvals import ApprovalDecision
from app.schemas.settlement import (
    BidSettlementLineItemOut,
    BidSettlementOut,
    BidSettlementScenarioOut,
    BidSettlementTradeOverrideOut,
    ExportRequest,
    FidelityReportOut,
    FxRateSet,
    LineCostUpdate,
    OriginalExportRequest,
    OutcomeRequest,
    ReasonCodeCreate,
    ReasonCodeUpdate,
    ScenarioCreate,
    SettlementDefaultsUpdate,
    SettlementReasonCodeOut,
    SimulateRequest,
    SimulateResult,
    TradeOverrideUpdate,
)
from app.services import settlement as settlement_service

router = APIRouter(tags=["bid-settlements"])

_HEADER_ROLES = (Role.LEAD_ESTIMATOR.value, Role.PROCUREMENT_HEAD.value, Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_LINE_ROLES = (Role.ESTIMATOR.value, *_HEADER_ROLES)
_OUTCOME_ROLES = (Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SUBMIT_ROLES = (Role.BD_DIRECTOR.value, Role.MANAGING_DIRECTOR.value)
# decide's role requirement is dynamic (whichever tier the approval routed
# to -- bd_director or managing_director) and segregation-of-duties is
# enforced generically in app/services/approvals.py::decide, so this
# endpoint uses CurrentUser rather than a static Depends(require_roles(...)),
# same reasoning as app/api/v1/routes/approvals.py's own decide endpoint.


def _to_out(settlement, lines, trade_overrides) -> BidSettlementOut:
    out = BidSettlementOut.model_validate(settlement)
    out.lines = [BidSettlementLineItemOut.model_validate(line) for line in lines]
    out.trade_overrides = [BidSettlementTradeOverrideOut.model_validate(row) for row in trade_overrides]
    return out


@router.post("/projects/{project_id}/bid-settlements", response_model=BidSettlementOut, status_code=201)
async def build_settlement_draft_endpoint(
    project_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    settlement = await settlement_service.build_settlement_draft(session, ctx, project_id)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement.id)
    return _to_out(settlement, lines, trade_overrides)


@router.get("/projects/{project_id}/bid-settlements", response_model=list[BidSettlementOut])
async def list_settlements_endpoint(
    project_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BidSettlementOut]:
    settlements = await settlement_service.list_settlements(session, project_id)
    return [BidSettlementOut.model_validate(s) for s in settlements]


@router.get("/bid-settlements/{settlement_id}", response_model=BidSettlementOut)
async def get_settlement_endpoint(
    settlement_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> BidSettlementOut:
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.patch("/bid-settlements/{settlement_id}/defaults", response_model=BidSettlementOut)
async def update_settlement_defaults_endpoint(
    settlement_id: UUID,
    data: SettlementDefaultsUpdate,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    await settlement_service.set_defaults(session, ctx, settlement_id, data)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.put("/bid-settlements/{settlement_id}/trade-overrides/{trade_node_id}", response_model=BidSettlementTradeOverrideOut)
async def set_trade_override_endpoint(
    settlement_id: UUID,
    trade_node_id: UUID,
    data: TradeOverrideUpdate,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementTradeOverrideOut:
    row = await settlement_service.set_trade_override(session, ctx, settlement_id, trade_node_id, data)
    return BidSettlementTradeOverrideOut.model_validate(row)


@router.patch("/bid-settlements/{settlement_id}/lines/{line_id}", response_model=BidSettlementLineItemOut)
async def update_settlement_line_endpoint(
    settlement_id: UUID,
    line_id: UUID,
    data: LineCostUpdate,
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementLineItemOut:
    line = await settlement_service.set_line_cost(session, ctx, settlement_id, line_id, data)
    return BidSettlementLineItemOut.model_validate(line)


@router.post("/bid-settlements/{settlement_id}/lines/{line_id}/fx-rate", response_model=BidSettlementLineItemOut)
async def set_line_fx_rate_endpoint(
    settlement_id: UUID,
    line_id: UUID,
    data: FxRateSet,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementLineItemOut:
    line = await settlement_service.set_line_fx_rate(session, ctx, settlement_id, line_id, data)
    return BidSettlementLineItemOut.model_validate(line)


@router.post("/bid-settlements/{settlement_id}/refresh-quantities", response_model=BidSettlementOut)
async def refresh_quantities_endpoint(
    settlement_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    await settlement_service.refresh_quantities(session, ctx, settlement_id)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.post("/bid-settlements/{settlement_id}/simulate", response_model=SimulateResult)
async def simulate_settlement_endpoint(
    settlement_id: UUID,
    data: SimulateRequest,
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> SimulateResult:
    return await settlement_service.simulate(session, ctx, settlement_id, data)


@router.post("/bid-settlements/{settlement_id}/scenarios", response_model=BidSettlementScenarioOut, status_code=201)
async def save_scenario_endpoint(
    settlement_id: UUID,
    data: ScenarioCreate,
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementScenarioOut:
    scenario = await settlement_service.save_scenario(session, ctx, settlement_id, data)
    return BidSettlementScenarioOut.model_validate(scenario)


@router.get("/bid-settlements/{settlement_id}/scenarios", response_model=list[BidSettlementScenarioOut])
async def list_scenarios_endpoint(
    settlement_id: UUID, ctx: RequestContext = CurrentUser, session: AsyncSession = Depends(get_session)
) -> list[BidSettlementScenarioOut]:
    scenarios = await settlement_service.list_scenarios(session, settlement_id)
    return [BidSettlementScenarioOut.model_validate(s) for s in scenarios]


@router.delete("/bid-settlements/{settlement_id}/scenarios/{scenario_id}", status_code=204, response_model=None)
async def delete_scenario_endpoint(
    settlement_id: UUID,
    scenario_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await settlement_service.delete_scenario(session, ctx, settlement_id, scenario_id)


@router.post("/bid-settlements/{settlement_id}/submit", response_model=BidSettlementOut)
async def submit_settlement_endpoint(
    settlement_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_SUBMIT_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    await settlement_service.submit_settlement(session, ctx, settlement_id)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.post("/bid-settlements/{settlement_id}/decide", response_model=BidSettlementOut)
async def decide_settlement_endpoint(
    settlement_id: UUID,
    data: ApprovalDecision,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    await settlement_service.decide_settlement(session, ctx, settlement_id, approve=data.approve, note=data.note)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.post("/bid-settlements/{settlement_id}/export")
async def export_settlement_endpoint(
    settlement_id: UUID,
    data: ExportRequest = ExportRequest(),
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    file_bytes, sha256, filename = await settlement_service.export_settlement(session, ctx, settlement_id, data)
    return Response(
        content=file_bytes, media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-File-SHA256": sha256},
    )


@router.post("/bid-settlements/{settlement_id}/outcome", response_model=BidSettlementOut)
async def record_outcome_endpoint(
    settlement_id: UUID,
    data: OutcomeRequest,
    ctx: RequestContext = Depends(require_roles(*_OUTCOME_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BidSettlementOut:
    await settlement_service.record_outcome(session, ctx, settlement_id, data)
    settlement, lines, trade_overrides = await settlement_service.get_settlement_detail(session, settlement_id)
    return _to_out(settlement, lines, trade_overrides)


@router.get("/settlement-reason-codes", response_model=list[SettlementReasonCodeOut])
async def list_reason_codes_endpoint(
    include_inactive: bool = False,
    ctx: RequestContext = CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[SettlementReasonCodeOut]:
    # include_inactive=false (default) is the win/loss-form's own use --
    # only ever-usable codes; the admin reason-codes screen passes true to
    # manage the full list, including ones it has deactivated.
    codes = await settlement_service.list_reason_codes(session, ctx, include_inactive=include_inactive)
    return [SettlementReasonCodeOut.model_validate(c) for c in codes]


@router.post("/settlement-reason-codes", response_model=SettlementReasonCodeOut, status_code=201)
async def create_reason_code_endpoint(
    data: ReasonCodeCreate,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> SettlementReasonCodeOut:
    row = await settlement_service.create_reason_code(session, ctx, data.code, data.label)
    return SettlementReasonCodeOut.model_validate(row)


@router.patch("/settlement-reason-codes/{reason_code_id}", response_model=SettlementReasonCodeOut)
async def update_reason_code_endpoint(
    reason_code_id: UUID,
    data: ReasonCodeUpdate,
    ctx: RequestContext = Depends(require_roles(*_HEADER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> SettlementReasonCodeOut:
    row = await settlement_service.update_reason_code(session, ctx, reason_code_id, label=data.label, is_active=data.is_active)
    return SettlementReasonCodeOut.model_validate(row)


@router.post("/bid-settlements/{settlement_id}/export-original/preview", response_model=FidelityReportOut)
async def preview_original_export_endpoint(
    settlement_id: UUID,
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> FidelityReportOut:
    report = await settlement_service.preview_original_export(session, ctx, settlement_id)
    return FidelityReportOut(**report)


@router.post("/bid-settlements/{settlement_id}/export-original")
async def export_original_endpoint(
    settlement_id: UUID,
    data: OriginalExportRequest = OriginalExportRequest(),
    ctx: RequestContext = Depends(require_roles(*_LINE_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    file_bytes, sha256, filename = await settlement_service.export_original_settlement(
        session, ctx, settlement_id, accept_loss=data.accept_loss
    )
    return Response(
        content=file_bytes, media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-File-SHA256": sha256},
    )
