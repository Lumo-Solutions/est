from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ESTIMATOR = "estimator"
    LEAD_ESTIMATOR = "lead_estimator"
    PROCUREMENT_HEAD = "procurement_head"
    BD_DIRECTOR = "bd_director"
    MANAGING_DIRECTOR = "managing_director"
    # Cross-tenant role, granted to platform operators only (not a tenant's
    # own staff). Its sole purpose today is reviewing inbound_emails rows
    # whose tenant could not be resolved at all (Module C2 change #1) -- it
    # is deliberately NOT added to WRITE_ROLES_MODULE_A/ALL_ROLES-based
    # per-tenant business checks, so it grants no tenant-scoped access.
    PLATFORM_ADMIN = "platform_admin"


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
    SEND = "send"


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


class ProcurementPackageStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    CLOSED = "closed"


class RfqStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    # Not produced by Module C1 (outbound dispatch only) -- reserved so C2
    # (inbound quotation ingestion, bid leveling) needs no further schema
    # change to record a vendor reply or an unanswered/lapsed RFQ.
    RESPONDED = "responded"
    EXPIRED = "expired"


class InboundEmailMatchStatus(StrEnum):
    """Outcome of app/procurement/inbound_match.py's reply-token/tenant
    lookup for one polled email. Independent of `needs_review` (auth/domain
    flags) -- see InboundEmail.needs_review."""

    MATCHED = "matched"
    QUARANTINED_NO_TOKEN = "quarantined_no_token"
    QUARANTINED_TOKEN_CLOSED = "quarantined_token_closed"
    QUARANTINED_UNKNOWN_TENANT = "quarantined_unknown_tenant"


class AttachmentSafetyStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED_TYPE = "rejected_type"
    REJECTED_SIZE = "rejected_size"
    REJECTED_PAGE_LIMIT = "rejected_page_limit"
    REJECTED_MACRO = "rejected_macro"
    REJECTED_ENCRYPTED = "rejected_encrypted"
    REJECTED_ARCHIVE = "rejected_archive"
    REJECTED_ZIP_BOMB = "rejected_zip_bomb"


class QuotationExtractionMethod(StrEnum):
    DETERMINISTIC_XLSX = "deterministic_xlsx"
    VLM_PDF = "vlm_pdf"
    VLM_IMAGE = "vlm_image"
    VLM_XLSX_OTHER = "vlm_xlsx_other"
    VLM_CSV = "vlm_csv"


class QuotationStatus(StrEnum):
    """Deliberately no ACCEPTED value -- acceptance is a per-line-item
    decision (QuotationLineItemStatus), never a whole-quotation rollup. This
    only ever moves to needs_review (the pricing sheet's row-id identity
    check failed -- SRS change #1) or rejected (an explicit reviewer
    action)."""

    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class QuotationLineItemStatus(StrEnum):
    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QuotationLineSource(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"


class LineItemMatchMethod(StrEnum):
    ROW_ID = "row_id"  # deterministic pricing-sheet hidden column (SRS change #1)
    FUZZY = "fuzzy"
    MANUAL = "manual"


class ExclusionFlagStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"


class AuthCheckResult(StrEnum):
    """One SPF/DKIM/DMARC verdict parsed from an Authentication-Results
    header (RFC 8601). UNKNOWN covers a missing/unparseable header -- treated
    the same as a failure for review purposes, never as an implicit pass."""

    PASS = "pass"
    FAIL = "fail"
    NONE = "none"
    UNKNOWN = "unknown"


WRITE_ROLES_MODULE_A = {
    Role.LEAD_ESTIMATOR,
    Role.PROCUREMENT_HEAD,
    Role.BD_DIRECTOR,
    Role.MANAGING_DIRECTOR,
}
ALL_ROLES = set(Role)
