from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ApprovalRequestCreate(BaseModel):
    project_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    amount: float
    currency: str = "AED"
    # Optional second routing signal for a policy tier with max_margin_pct
    # set (e.g. bid_submission) -- see app/services/approvals.py::route_tiers.
    # Ignored by every tier that doesn't define max_margin_pct.
    margin_pct: float | None = None
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
    amount: float
    currency: str
    status: str
    current_seq: int
    requested_by: UUID
    requested_at: datetime
    completed_at: datetime | None
    steps: list[ApprovalStepOut] = []


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
    min_amount: float = 0
    max_amount: float | None = None
    max_margin_pct: float | None = None
    required_role: str
    quorum: int = 1
    sla_hours: int | None = None
    requires_mfa: bool = True


class ApprovalPolicyTierOut(ORMModel):
    id: UUID
    policy_id: UUID
    seq: int
    min_amount: float
    max_amount: float | None
    max_margin_pct: float | None
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
