from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.common import JsonDecimal, ORMModel


class TenderPackageOut(ORMModel):
    id: UUID
    project_id: UUID
    label: str | None
    transmittal_ref: str | None
    received_date: date
    status: str
    file_count: int
    created_at: datetime


class TenderPackageAccepted(BaseModel):
    package_id: UUID
    file_count: int
    status: str


class ClassificationOut(ORMModel):
    id: UUID
    source: str
    doc_class: str
    sub_type: str | None
    confidence: JsonDecimal
    evidence: list
    metadata: dict = Field(validation_alias=AliasChoices("doc_metadata", "metadata"))
    is_current: bool
    created_at: datetime


class ProjectDocumentOut(ORMModel):
    id: UUID
    project_id: UUID
    package_id: UUID
    parent_document_id: UUID | None
    archive_path: str | None
    original_filename: str
    ext: str
    sha256: str
    size_bytes: int
    content_type_sniffed: str | None
    safety_status: str
    rejection_reason: str | None
    doc_class: str | None
    sub_type: str | None
    confidence: JsonDecimal | None
    title: str | None
    document_number: str | None
    revision_label: str | None
    metadata: dict = Field(validation_alias=AliasChoices("doc_metadata", "metadata"))
    evidence: list
    flags: list
    status: str
    error_message: str | None
    duplicate_of_id: UUID | None
    supersedes_id: UUID | None
    routed_kind: str | None
    routed_ref: dict
    classified_by: str | None = None
    auto_accepted: bool = False
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    created_at: datetime


class ProjectDocumentDetailOut(ProjectDocumentOut):
    classifications: list[ClassificationOut] = []


class DocumentPage(BaseModel):
    items: list[ProjectDocumentOut]
    total: int
    limit: int
    offset: int


class ReclassifyIn(BaseModel):
    doc_class: str
    sub_type: str | None = None
    drawing_type: str | None = None
    note: str | None = None
    # One-click "confirm or change": also routes the document under the new class (routed documents always re-route).
    confirm: bool = False


class BulkReclassifyIn(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=1000)
    doc_class: str
    sub_type: str | None = None
    drawing_type: str | None = None
    note: str | None = None
    confirm: bool = True


class EditMetadataIn(BaseModel):
    metadata: dict | None = None
    title: str | None = None
    document_number: str | None = None
    revision_label: str | None = None


class ExcludeIn(BaseModel):
    reason: str = Field(min_length=1)


class BulkConfirmIn(BaseModel):
    package_id: UUID | None = None
    document_ids: list[UUID] | None = None
    min_confidence: float | None = None


class ConfirmItemResult(BaseModel):
    id: UUID
    ok: bool
    status: str | None = None
    routed_kind: str | None = None
    error: str | None = None


class BulkConfirmOut(BaseModel):
    confirmed: int
    failed: int
    skipped: int
    results: list[ConfirmItemResult]


class AddendumLinkOut(ORMModel):
    id: UUID
    target_document_id: UUID | None
    reference_text: str
    action: str
    resolved: bool


class AddendumOut(ORMModel):
    id: UUID
    project_id: UUID
    document_id: UUID
    package_id: UUID | None
    addendum_no: str | None
    issue_date: str | None
    title: str | None
    summary: str | None
    routed_at: datetime
    flagged_settlement_ids: list
    links: list[AddendumLinkOut] = []
    # Settlements (of the flagged ids) that are still draft/submitted AND have not been
    # refreshed since this addendum was routed: what the settlement banner keys on.
    open_settlement_ids: list[UUID] = []


class BoqPrefillOut(BaseModel):
    document_id: UUID
    filename: str
    sheet_name: str | None
    header_row: int | None
    sheet_names: list[str]
    suggested_mapping: dict


class TenderClassOut(BaseModel):
    code: str
    label: str
    default_label: str
    enabled: bool
    sort_order: int


class TenderClassUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    sort_order: int | None = None


# ------------------------------------------------------------------ the document tree (the project page)
class TreeItem(BaseModel):
    id: UUID
    package_id: UUID
    name: str
    path: str | None
    ext: str
    size_bytes: int
    doc_class: str | None
    discipline: str | None
    drawing_type: str | None
    unit_type: str | None
    document_number: str | None
    title: str | None
    revision: str | None
    sheet_number: str | None
    scale: str | None
    confidence: float | None
    status: str
    # queued | reading | classified | extracting | ready | needs_check | failed | excluded
    display_status: str
    status_reason: str | None
    classified_by: str | None
    # Who decided the class: ai (auto-accepted), rules, or user (confirmed or changed by a person).
    decided_by: str | None
    auto_accepted: bool
    flags: list[str]
    routed_kind: str | None
    drawing_id: UUID | None
    evidence_quote: str | None
    evidence_page: int | None
    ai_note: str | None
    supersedes: list[str] = []
    created_at: datetime


class TreeSummary(BaseModel):
    total: int
    by_display_status: dict[str, int]
    by_class: dict[str, int]
    needs_check: int
    in_progress: int
    drawings_total: int
    drawings_ready: int
    boq_documents: list[UUID]
    addenda: int
    packages_processing: int
    auto_accept_min: float
    ai_available: bool
    ai_message: str | None = None


class TreeOut(BaseModel):
    items: list[TreeItem]
    summary: TreeSummary


class IntakeSettingsIn(BaseModel):
    auto_accept_min: float = Field(ge=0.5, le=1.0)


class IntakeSettingsOut(BaseModel):
    auto_accept_min: float
    default_auto_accept_min: float = 0.85
