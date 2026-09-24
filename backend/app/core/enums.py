from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ESTIMATOR = "estimator"
    LEAD_ESTIMATOR = "lead_estimator"
    PROCUREMENT_HEAD = "procurement_head"
    BD_DIRECTOR = "bd_director"
    MANAGING_DIRECTOR = "managing_director"


class AuditAction(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    EXPORT = "export"
    LOGIN = "login"
    LOGOUT = "logout"
    MERGE = "merge"
    IMPORT = "import"
    DOWNLOAD = "download"


class VendorStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    BLACKLISTED = "blacklisted"
    MERGED = "merged"


class DuplicateCandidateStatus(StrEnum):
    OPEN = "open"
    CONFIRMED_DUPLICATE = "confirmed_duplicate"
    NOT_DUPLICATE = "not_duplicate"
    MERGED = "merged"


class PrequalificationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CONDITIONAL = "conditional"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    BLACKLISTED = "blacklisted"


class CertificateStatus(StrEnum):
    VALID = "valid"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PENDING_VERIFICATION = "pending_verification"


class CostItemType(StrEnum):
    MATERIAL = "material"
    LABOUR = "labour"
    EQUIPMENT = "equipment"
    SUBCONTRACT = "subcontract"
    COMPOSITE = "composite"
    INDIRECT = "indirect"


class RateComponentType(StrEnum):
    MATERIAL = "material"
    LABOUR = "labour"
    EQUIPMENT = "equipment"
    SUBCONTRACTOR = "subcontractor"
    INDIRECT = "indirect"


class RateSource(StrEnum):
    MANUAL = "manual"
    QUOTATION = "quotation"
    AWARD = "award"
    INDEX_ADJUSTMENT = "index_adjustment"
    IMPORT = "import"


class ApprovalEntityType(StrEnum):
    COST_RATE_CHANGE = "cost_rate_change"
    VENDOR_ONBOARDING = "vendor_onboarding"
    PREQUALIFICATION = "prequalification"
    BID_SUBMISSION = "bid_submission"
    RFQ_AWARD = "rfq_award"
    EXPORT = "export"


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ApprovalStepStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ProjectStatus(StrEnum):
    PROSPECT = "prospect"
    TENDERING = "tendering"
    SUBMITTED = "submitted"
    AWARDED = "awarded"
    LOST = "lost"
    ARCHIVED = "archived"


class DrawingKind(StrEnum):
    VECTOR_PDF = "vector_pdf"
    SCANNED_PDF = "scanned_pdf"
    DXF = "dxf"
    UNKNOWN = "unknown"


class DrawingStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    INDEXING = "indexing"
    EXTRACTING = "extracting"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"
    PARTIAL = "partial"


class ScaleSource(StrEnum):
    TITLE_BLOCK_TEXT = "title_block_text"
    DIMENSION_MATCH = "dimension_match"
    SCALE_BAR = "scale_bar"
    DXF_UNITS = "dxf_units"
    MANUAL_TWO_POINT = "manual_two_point"
    UNKNOWN = "unknown"


class ExtractionJobType(StrEnum):
    INDEX_SHEETS = "index_sheets"
    EXTRACT_TITLE_BLOCK = "extract_title_block"
    DERIVE_SCALE = "derive_scale"
    EMBED_SHEET = "embed_sheet"
    EXTRACT_GEOMETRY = "extract_geometry"
    FINALIZE = "finalize"


class ExtractionJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


WRITE_ROLES_MODULE_A = {
    Role.LEAD_ESTIMATOR,
    Role.PROCUREMENT_HEAD,
    Role.BD_DIRECTOR,
    Role.MANAGING_DIRECTOR,
}
ALL_ROLES = set(Role)
