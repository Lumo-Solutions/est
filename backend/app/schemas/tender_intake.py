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
    note: str | None = None


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
