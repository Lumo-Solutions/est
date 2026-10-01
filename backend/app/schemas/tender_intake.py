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
    expected_count: int | None = None
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


class DocFilter(BaseModel):
    """Which documents of a project: the one vocabulary shared by the paged list, the group counts and the bulk
    actions, so "every file that matches" means the same thing on screen and on the server. `none` stands for
    "not set" in doc_class / discipline / drawing_type."""

    package_id: UUID | None = None
    doc_class: str | None = None
    discipline: str | None = None
    drawing_type: str | None = None
    display_status: str | None = None
    decided_by: str | None = None
    flag: str | None = None
    exclude_flags: list[str] = []
    # True: only files that have a proposed class; False: only those that have none.
    has_class: bool | None = None
    # Exact upload folder ('' = files at the top level); with include_subfolders, that folder and everything below it.
    folder: str | None = None
    include_subfolders: bool = False
    q: str | None = None


class BulkReclassifyIn(BaseModel):
    # Either explicit ids, or a filter (every matching file, a chunk per request; the response carries the cursor).
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)
    filter: DocFilter | None = None
    cursor: str | None = None
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
    # Confirm every file matching the filter (server-side, a chunk per request). `cursor` continues a previous call.
    filter: DocFilter | None = None
    cursor: str | None = None


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
    # Filter-based calls only: how many files matched when the call started, and where to continue (None = done).
    matched: int | None = None
    next_cursor: str | None = None


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


class TreeBoqDoc(BaseModel):
    id: UUID
    name: str


class TreeSummary(BaseModel):
    total: int
    by_display_status: dict[str, int]
    by_class: dict[str, int]
    needs_check: int
    in_progress: int
    # Registered files whose bytes have not arrived yet (a resumable upload in progress).
    pending_upload: int = 0
    drawings_total: int
    drawings_ready: int
    boq_documents: list[TreeBoqDoc]
    first_drawing_id: UUID | None = None
    addenda: int
    packages_processing: int
    auto_accept_min: float
    ai_available: bool
    ai_message: str | None = None


class GroupCount(BaseModel):
    doc_class: str | None
    discipline: str | None
    drawing_type: str | None
    count: int


class FolderCount(BaseModel):
    folder: str
    count: int


class PackageProgress(BaseModel):
    id: UUID
    label: str | None
    # uploading | processing | ready | failed | paused | cancelled
    status: str
    created_at: datetime
    expected_count: int
    registered: int
    uploaded: int
    # Uploaded files that have not been read yet (queued or being read).
    waiting: int
    pending_upload: int
    # An external AI provider would read it and nobody confirmed the estimated cost yet: it is not started.
    awaiting_cost_confirmation: bool = False


class TreeOut(BaseModel):
    summary: TreeSummary
    groups: list[GroupCount]
    folders: list[FolderCount]
    packages: list[PackageProgress]


class TreeItemPage(BaseModel):
    items: list[TreeItem]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ resumable upload
class RegisterFileIn(BaseModel):
    # Path relative to the dropped folder ("Drawings/Roads/R-101.pdf"); a lone file is just its name.
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class RegisterPackageIn(BaseModel):
    # Continue this pack. Without it the server resumes the project's unfinished upload (if any) or starts a new pack.
    package_id: UUID | None = None
    new_package: bool = False
    label: str | None = None
    transmittal_ref: str | None = None
    received_date: date | None = None
    # How many files the whole drop holds (the request carries only a batch of them): the pack cap and the "X of N"
    # progress key on this.
    total_files: int | None = Field(default=None, ge=1)
    files: list[RegisterFileIn] = Field(min_length=1, max_length=1000)


class RegisteredFileOut(BaseModel):
    path: str
    sha256: str
    document_id: UUID | None
    # pending: send the bytes | uploaded: already on the server (skip) | same_as_another: same bytes as a file
    # that is being sent, nothing to send | rejected: not accepted, see reason
    state: str
    upload: bool
    reason: str | None = None


class RegisterPackageOut(BaseModel):
    package_id: UUID
    status: str
    resumed: bool
    expected_count: int | None
    files: list[RegisteredFileOut]


class UploadResult(BaseModel):
    document_id: UUID
    state: str
    package_status: str
    registered: int
    uploaded: int
    expected_count: int | None


class PackageControlOut(BaseModel):
    package_id: UUID
    status: str
    cancelled_documents: int = 0


class IntakeSettingsIn(BaseModel):
    auto_accept_min: float | None = Field(default=None, ge=0.5, le=1.0)
    # Disciplines whose drawings are measured automatically when intake routes them (default: none).
    auto_measure_disciplines: list[str] | None = None


class IntakeSettingsOut(BaseModel):
    auto_accept_min: float
    default_auto_accept_min: float = 0.85
    auto_measure_disciplines: list[str] = []
