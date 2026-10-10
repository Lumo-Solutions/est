from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import JsonDecimal, ORMModel


class ApprovalRequestCreate(BaseModel):
    project_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    amount: Decimal
    currency: str = "AED"
    # Optional second routing signal for a policy tier with max_margin_pct
    # set (e.g. bid_submission) -- see app/services/approvals.py::route_tiers.
    # Ignored by every tier that doesn't define max_margin_pct. Decimal, not
    # float: route_tiers()/_tier_matches() compare this directly against
    # ApprovalPolicyTier.max_margin_pct with no float conversion anywhere in
    # the path, so a 3dp-quantized margin (e.g. 7.995) stays exact.
    margin_pct: Decimal | None = None
    payload_snapshot: dict | None = None


class ApprovalStepOut(ORMModel):
    id: UUID
    seq: int
    required_role: str
    status: str
    decided_by: UUID | None
    decided_at: datetime | None
    decision_note: str | None


class ApprovalRequestOut(ORMModel):
    id: UUID
    project_id: UUID | None
    entity_type: str
    entity_id: UUID
    amount: JsonDecimal
    currency: str
    status: str
    current_seq: int
    requested_by: UUID
    requested_at: datetime
    completed_at: datetime | None
    steps: list[ApprovalStepOut] = []
    # Display context, filled by app/services/approvals.py::enrich (None when
    # not enriched, e.g. the create endpoint's response).
    project_code: str | None = None
    project_name: str | None = None
    requested_by_name: str | None = None
    # Role of the step currently waiting (None once the request is closed).
    waiting_role: str | None = None
    # Settlement version and margin-on-sell (3dp) for bid_submission only.
    settlement_version_no: int | None = None
    margin_on_sell_pct: JsonDecimal | None = None
    # Caller-relative: "actionable" | "awaiting_other" (the caller submitted
    # it) | "decided" | "other".
    view_state: str | None = None
    payload_snapshot: dict | None = None


class ApprovalWithdraw(BaseModel):
    reason: str | None = None


class ApprovalInboxOut(BaseModel):
    pending: list[ApprovalRequestOut]
    recent: list[ApprovalRequestOut]


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = None


# --------------------------------------------------------------------------
# Phase 8f: admin CRUD for the policy tables app/services/approvals.py's
# _active_policy()/route_tiers() already read live -- these were
# previously DB-configurable in name only (no API existed to view or
# change them; only app/cli.py's dev-seed ever wrote a row). See
# docs/module-frontend-phase8f-plan.md.
# --------------------------------------------------------------------------


class ApprovalPolicyTierIn(BaseModel):
    seq: int
    min_amount: Decimal = Decimal("0")
    max_amount: Decimal | None = None
    max_margin_pct: Decimal | None = None
    required_role: str
    quorum: int = 1
    sla_hours: int | None = None
    requires_mfa: bool = True


class ApprovalPolicyTierOut(ORMModel):
    id: UUID
    policy_id: UUID
    seq: int
    min_amount: JsonDecimal
    max_amount: JsonDecimal | None
    max_margin_pct: JsonDecimal | None
    required_role: str
    quorum: int
    sla_hours: int | None
    requires_mfa: bool


class ApprovalPolicyCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    mode: str = "sequential_up_to_tier"
    tiers: list[ApprovalPolicyTierIn] = Field(min_length=1)


class ApprovalPolicyOut(ORMModel):
    id: UUID
    entity_type: str
    name: str
    version: int
    mode: str
    is_active: bool
    tiers: list[ApprovalPolicyTierOut] = []


class ApprovalPolicySetActive(BaseModel):
    is_active: bool
