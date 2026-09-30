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

# Drawing discipline (stored in ``sub_type``). The first eleven are what the AI is asked for; ``civil_infra`` and
# ``other`` are kept so documents classified before AI-first intake stay valid.
DRAWING_DISCIPLINES = (
    "roads_civil", "stormwater", "sewer", "water_supply", "irrigation", "electrical_lighting", "telecom",
    "landscape", "architectural", "structural", "mep",
)
DRAWING_SUB_TYPES = (*DRAWING_DISCIPLINES, "civil_infra", "other")
DISCIPLINE_LABELS: dict[str, str] = {
    "roads_civil": "Roads / civil", "stormwater": "Stormwater drainage", "sewer": "Sewer", "water_supply": "Water supply",
    "irrigation": "Irrigation", "electrical_lighting": "Electrical / street lighting", "telecom": "Telecom",
    "landscape": "Landscape", "architectural": "Architectural", "structural": "Structural", "mep": "MEP",
    "civil_infra": "Civil / infrastructure", "other": "Other discipline",
}
# What kind of sheet a drawing is (stored in ``metadata.drawing_type``).
DRAWING_TYPES = (
    "location_plan", "general_arrangement", "plan_profile", "cross_sections", "typical_details", "schedules", "setting_out",
)
DRAWING_TYPE_LABELS: dict[str, str] = {
    "location_plan": "Location / key plan", "general_arrangement": "General arrangement / layout",
    "plan_profile": "Plan & profile / longitudinal section", "cross_sections": "Cross sections",
    "typical_details": "Typical details", "schedules": "Schedules", "setting_out": "Setting-out",
}
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


class Decider(StrEnum):
    """Who decided a document's class, as shown in the tree and written to the audit trail."""

    AI = "ai"
    RULES = "rules"
    USER = "user"


class Flag(StrEnum):
    DUPLICATE = "duplicate"
    NOT_MEASURABLE = "not_measurable"
    CONVERT_TO_DXF = "convert_to_dxf"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"
    MODEL_UNAVAILABLE = "model_unavailable"
    REVISION_OF = "revision_of"
    # The AI could not be used for this file (off, not configured, over budget, failed): rules decided.
    RULES_FALLBACK = "rules_fallback"
    # Text in the file tried to instruct the classifier; it was ignored and the file needs a person's check.
    INJECTION_SUSPECTED = "injection_suspected"


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
