"""Shared vocabulary for tender document intake (docs/tender-intake-plan.md)."""

from __future__ import annotations

from enum import StrEnum

from app.core.enums import Role


class DocClass(StrEnum):
    DRAWING = "drawing"
    BOQ = "boq"
    ADDENDUM = "addendum"
    SPECIFICATION = "specification"
    CONTRACT = "contract"
    TENDER_INSTRUCTIONS = "tender_instructions"
    TENDER_FORMS = "tender_forms"
    CLARIFICATION = "clarification"
    PROGRAMME = "programme"
    SITE_INVESTIGATION = "site_investigation"
    CORRESPONDENCE = "correspondence"
    OTHER = "other"


DEFAULT_CLASS_LABELS: dict[str, str] = {
    DocClass.DRAWING.value: "Drawing",
    DocClass.BOQ.value: "BOQ",
    DocClass.ADDENDUM.value: "Addendum",
    DocClass.SPECIFICATION.value: "Specification",
    DocClass.CONTRACT.value: "Contract / Conditions",
    DocClass.TENDER_INSTRUCTIONS.value: "Tender instructions",
    DocClass.TENDER_FORMS.value: "Tender forms and bonds",
    DocClass.CLARIFICATION.value: "Clarification / RFI response",
    DocClass.PROGRAMME.value: "Programme / schedule",
    DocClass.SITE_INVESTIGATION.value: "Site investigation / geotechnical",
    DocClass.CORRESPONDENCE.value: "Correspondence",
    DocClass.OTHER.value: "Other",
}

DRAWING_SUB_TYPES = ("civil_infra", "architectural", "structural", "mep", "landscape", "other")
ALL_CLASSES = tuple(c.value for c in DocClass)


class DocStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    ROUTED = "routed"
    FAILED = "failed"
    REJECTED = "rejected"
    EXCLUDED = "excluded"
    ARCHIVE = "archive"


class PackageStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ClassificationSource(StrEnum):
    RULES = "rules"
    MODEL = "model"
    USER = "user"


class Flag(StrEnum):
    DUPLICATE = "duplicate"
    NOT_MEASURABLE = "not_measurable"
    CONVERT_TO_DXF = "convert_to_dxf"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"
    MODEL_UNAVAILABLE = "model_unavailable"
    REVISION_OF = "revision_of"


# "lead_estimator+" written out (no rank comparison exists in this codebase).
UPLOAD_ROLES = (
    Role.ESTIMATOR.value,
    Role.LEAD_ESTIMATOR.value,
    Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value,
    Role.MANAGING_DIRECTOR.value,
)
CONFIRM_ROLES = (
    Role.LEAD_ESTIMATOR.value,
    Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value,
    Role.MANAGING_DIRECTOR.value,
)
CLASS_ADMIN_ROLES = (Role.MANAGING_DIRECTOR.value,)

REGISTER_CLASSES = (
    DocClass.SPECIFICATION.value,
    DocClass.CONTRACT.value,
    DocClass.TENDER_INSTRUCTIONS.value,
    DocClass.TENDER_FORMS.value,
    DocClass.CLARIFICATION.value,
    DocClass.PROGRAMME.value,
    DocClass.SITE_INVESTIGATION.value,
    DocClass.CORRESPONDENCE.value,
    DocClass.OTHER.value,
)
