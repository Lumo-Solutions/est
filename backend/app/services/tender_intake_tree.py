"""The project page's document tree, built for a pack of thousands of files.

Nothing here loads a whole project's documents. The page asks for

* a **summary** (counts per display status and class, the drawing/discipline/type group counts, the folder counts and
  the packs, all worked out by the database), and
* **pages of documents** for one group or filter at a time (`list_tree_items`), which the client virtualises.

A person reads a *display status* (queued, reading, classified, extracting, ready, needs check, failed, excluded),
worked out from the document and, for a routed drawing, from the drawing's own extraction status. The same rule
exists twice: `_display` (Python, for the rows of one page, with the reason text) and `display_status_expr` (SQL, for
counting and filtering). tests/integration/test_intake_scale.py asserts that they agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, and_, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession

from app.intake.constants import Decider, DocClass, DocStatus, Flag, PackageStatus
from app.models.takeoff import Drawing
from app.models.tender_intake import Addendum, ProjectDocument, TenderPackage
from app.schemas.tender_intake import (
    DocFilter,
    FolderCount,
    GroupCount,
    PackageProgress,
    TreeBoqDoc,
    TreeItem,
    TreeOut,
    TreeSummary,
)
from app.services.tender_intake import (
    AUTO_ACCEPT_BLOCKING_FLAGS,
    ROUTABLE_EXTS,
    get_auto_accept_min,
    would_auto_accept,
)

_DRAWING_IN_PROGRESS = ("uploaded", "queued", "converting", "indexing", "extracting", "embedding")
IN_PROGRESS = ("queued", "reading", "classified", "extracting")
NO_CLASS = "none"
MAX_BOQ_DOCS = 20
MAX_FOLDERS = 5_000


# ----------------------------------------------------------------------------- one row (Python)
def _evidence_quote(doc: ProjectDocument) -> tuple[str | None, int | None]:
    for ev in doc.evidence or []:
        if ev.get("rule") == "model" and ev.get("matched"):
            return str(ev["matched"])[:200], ev.get("page")
    for ev in doc.evidence or []:
        if ev.get("matched"):
            return str(ev["matched"])[:200], ev.get("page")
    return None, None


def _decided_by(doc: ProjectDocument) -> str | None:
    if doc.auto_accepted:
        return Decider.AI.value
    if doc.confirmed_by is not None or doc.classified_by == Decider.USER.value:
        return Decider.USER.value
    return doc.classified_by


def _display(doc: ProjectDocument, threshold: float, drawings: dict[UUID, Drawing]) -> tuple[str, str | None]:
    status = doc.status
    if status == DocStatus.PENDING_UPLOAD.value:
        return "uploading", None
    if status == DocStatus.RECEIVED.value:
        return "queued", None
    if status == DocStatus.PROCESSING.value:
        return "reading", None
    if status == DocStatus.EXCLUDED.value:
        return "excluded", doc.error_message
    if status == DocStatus.REJECTED.value:
        return "failed", doc.rejection_reason or "rejected by the safety check"
    if status == DocStatus.FAILED.value:
        return "failed", doc.error_message or "processing failed"
    if status == DocStatus.PROPOSED.value:
        if would_auto_accept(doc, threshold):
            return "classified", None  # about to be accepted and routed
        reason = doc.error_message
        if not reason:
            flags = set(doc.flags or [])
            if Flag.INJECTION_SUSPECTED.value in flags:
                reason = "The file contains text aimed at the classifier; please check it"
            elif Flag.RULES_FALLBACK.value in flags:
                reason = (doc.doc_metadata or {}).get("ai_unavailable_reason")
                reason = f"Classified by rules ({reason})" if reason else "Classified by rules"
            elif Flag.CONFLICT.value in flags:
                reason = "The AI and the automatic rules disagree"
            elif float(doc.confidence or 0) < threshold:
                reason = "Confidence is below the auto-accept threshold"
        return "needs_check", reason
    # confirmed / routed
    if doc.routed_kind == "drawing":
        drawing_id = doc.routed_ref.get("drawing_id")
        drawing = drawings.get(UUID(drawing_id)) if drawing_id else None
        if drawing is None:
            return "ready", None
        if drawing.status in _DRAWING_IN_PROGRESS:
            return "extracting", None
        if drawing.status == "failed":
            return "failed", drawing.error_message or "drawing extraction failed"
        if drawing.status == "needs_conversion":
            return "needs_check", "The DWG needs conversion before it can be measured"
        if drawing.status == "partial":
            return "ready", "Some sheets could not be fully read"
        return "ready", None
    if doc.routed_kind == "not_measurable":
        return "ready", str(doc.routed_ref.get("note") or "not measurable")
    if doc.routed_kind == "duplicate":
        return "ready", "Identical to another file in this project"
    return "ready", None


def tree_item(doc: ProjectDocument, threshold: float, drawings: dict[UUID, Drawing]) -> TreeItem:
    display, reason = _display(doc, threshold, drawings)
    md = doc.doc_metadata or {}
    quote, page = _evidence_quote(doc)
    is_drawing = doc.doc_class == DocClass.DRAWING.value
    return TreeItem(
        id=doc.id, package_id=doc.package_id, name=doc.original_filename, path=doc.archive_path, ext=doc.ext,
        size_bytes=doc.size_bytes, doc_class=doc.doc_class, discipline=doc.sub_type if is_drawing else None,
        drawing_type=md.get("drawing_type") if is_drawing else None, unit_type=md.get("unit_type") if is_drawing else None,
        document_number=doc.document_number, title=doc.title, revision=doc.revision_label,
        sheet_number=md.get("sheet_number"), scale=md.get("scale"),
        confidence=float(doc.confidence) if doc.confidence is not None else None, status=doc.status,
        display_status=display, status_reason=reason, classified_by=doc.classified_by, decided_by=_decided_by(doc),
        auto_accepted=doc.auto_accepted, flags=list(doc.flags or []), routed_kind=doc.routed_kind,
        drawing_id=UUID(doc.routed_ref["drawing_id"]) if doc.routed_kind == "drawing" and doc.routed_ref.get("drawing_id") else None,
        evidence_quote=quote, evidence_page=page, ai_note=md.get("ai_unavailable_reason"),
        supersedes=[str(x) for x in md.get("supersedes", [])] if doc.doc_class == DocClass.ADDENDUM.value else [],
        created_at=doc.created_at,
    )


# ----------------------------------------------------------------------------- the same rules in SQL
def _drawing_join_id():
    """The routed drawing's id as a uuid, NULL unless the document is routed as a drawing (the CASE keeps Postgres
    from casting some other routed_ref value)."""
    return cast(
        case((ProjectDocument.routed_kind == "drawing", ProjectDocument.routed_ref["drawing_id"].astext), else_=None),
        PG_UUID(as_uuid=True),
    )


def would_auto_accept_expr(threshold: float):
    routable = [and_(ProjectDocument.doc_class == cls, ProjectDocument.ext.in_(sorted(exts))) for cls, exts in ROUTABLE_EXTS.items()]
    ext_ok = or_(ProjectDocument.doc_class.is_(None), ProjectDocument.doc_class.notin_(list(ROUTABLE_EXTS)), *routable)
    return and_(
        ProjectDocument.status == DocStatus.PROPOSED.value,
        ProjectDocument.classified_by == Decider.AI.value,
        ProjectDocument.safety_status == "accepted",
        func.coalesce(ProjectDocument.confidence, 0) >= threshold,
        ~ProjectDocument.flags.has_any(pg_array(sorted(AUTO_ACCEPT_BLOCKING_FLAGS))),
        ext_ok,
    )


def display_status_expr(threshold: float):
    """SQL twin of `_display` (without the reason text). Needs `Drawing` outer-joined on `_drawing_join_id()`."""
    routed_state = case(
        (
            and_(ProjectDocument.routed_kind == "drawing", Drawing.id.is_not(None)),
            case(
                (Drawing.status.in_(_DRAWING_IN_PROGRESS), "extracting"),
                (Drawing.status == "failed", "failed"),
                (Drawing.status == "needs_conversion", "needs_check"),
                else_="ready",
            ),
        ),
        else_="ready",
    )
    return case(
        (ProjectDocument.status == DocStatus.PENDING_UPLOAD.value, "uploading"),
        (ProjectDocument.status == DocStatus.RECEIVED.value, "queued"),
        (ProjectDocument.status == DocStatus.PROCESSING.value, "reading"),
        (ProjectDocument.status == DocStatus.EXCLUDED.value, "excluded"),
        (ProjectDocument.status.in_([DocStatus.REJECTED.value, DocStatus.FAILED.value]), "failed"),
        (ProjectDocument.status == DocStatus.PROPOSED.value, case((would_auto_accept_expr(threshold), "classified"), else_="needs_check")),
        else_=routed_state,
    )


def decided_by_expr():
    return case(
        (ProjectDocument.auto_accepted.is_(True), Decider.AI.value),
        (or_(ProjectDocument.confirmed_by.is_not(None), ProjectDocument.classified_by == Decider.USER.value), Decider.USER.value),
        else_=ProjectDocument.classified_by,
    )


def _folder():
    """The directory part of the upload path ('' for a file at the top level)."""
    path = func.coalesce(ProjectDocument.archive_path, "")
    return case((func.strpos(path, "/") > 0, func.regexp_replace(path, "/[^/]*$", "")), else_="")


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_filter(stmt: Select, project_id: UUID, f: DocFilter, threshold: float, *, include_pending: bool = False) -> Select:
    """Restricts a `select(ProjectDocument, ...)` (with Drawing outer-joined) to the documents matching `f`.
    Archive parents are never listed, and neither are files that have not arrived yet unless asked for."""
    stmt = stmt.where(ProjectDocument.project_id == project_id, ProjectDocument.status != DocStatus.ARCHIVE.value)
    if not include_pending:
        stmt = stmt.where(ProjectDocument.status != DocStatus.PENDING_UPLOAD.value)
    if f.package_id:
        stmt = stmt.where(ProjectDocument.package_id == f.package_id)
    if f.doc_class:
        stmt = stmt.where(ProjectDocument.doc_class.is_(None) if f.doc_class == NO_CLASS else ProjectDocument.doc_class == f.doc_class)
    if f.has_class is not None:
        stmt = stmt.where(ProjectDocument.doc_class.is_not(None) if f.has_class else ProjectDocument.doc_class.is_(None))
    if f.discipline:
        stmt = stmt.where(ProjectDocument.sub_type.is_(None) if f.discipline == NO_CLASS else ProjectDocument.sub_type == f.discipline)
    if f.drawing_type:
        dt = ProjectDocument.doc_metadata["drawing_type"].astext
        stmt = stmt.where(dt.is_(None) if f.drawing_type == NO_CLASS else dt == f.drawing_type)
    if f.display_status:
        stmt = stmt.where(display_status_expr(threshold) == f.display_status)
    if f.decided_by:
        decided = decided_by_expr()
        if f.decided_by == Decider.RULES.value:
            stmt = stmt.where(or_(decided == Decider.RULES.value, and_(decided.is_(None), ProjectDocument.flags.contains([Flag.RULES_FALLBACK.value]))))
        else:
            stmt = stmt.where(decided == f.decided_by)
    if f.flag:
        stmt = stmt.where(ProjectDocument.flags.contains([f.flag]))
    if f.exclude_flags:
        stmt = stmt.where(~ProjectDocument.flags.has_any(pg_array(list(f.exclude_flags))))
    if f.folder is not None:
        folder = _folder()
        if f.include_subfolders and f.folder != "":
            stmt = stmt.where(or_(folder == f.folder, folder.like(_like_escape(f.folder) + "/%", escape="\\")))
        elif not f.include_subfolders:
            stmt = stmt.where(folder == f.folder)
    if f.q and f.q.strip():
        like = f"%{_like_escape(f.q.strip())}%"
        stmt = stmt.where(
            or_(
                ProjectDocument.original_filename.ilike(like, escape="\\"),
                ProjectDocument.archive_path.ilike(like, escape="\\"),
                ProjectDocument.title.ilike(like, escape="\\"),
                ProjectDocument.document_number.ilike(like, escape="\\"),
            )
        )
    return stmt


def _base_select(*cols):
    return select(*cols).select_from(ProjectDocument).outerjoin(Drawing, Drawing.id == _drawing_join_id())


# ----------------------------------------------------------------------------- pages of documents
async def list_tree_items(
    session: AsyncSession, project_id: UUID, f: DocFilter, *, limit: int, offset: int
) -> tuple[list[TreeItem], int]:
    threshold = await get_auto_accept_min(session)
    count_stmt = apply_filter(_base_select(func.count()), project_id, f, threshold)
    total = (await session.execute(count_stmt)).scalar_one()
    rows_stmt = (
        apply_filter(_base_select(ProjectDocument), project_id, f, threshold)
        .order_by(ProjectDocument.created_at, ProjectDocument.original_filename, ProjectDocument.id)
        .limit(limit)
        .offset(offset)
    )
    docs = list((await session.execute(rows_stmt)).scalars().all())
    drawing_ids = [UUID(d.routed_ref["drawing_id"]) for d in docs if d.routed_kind == "drawing" and d.routed_ref.get("drawing_id")]
    drawings: dict[UUID, Drawing] = {}
    if drawing_ids:
        drawings = {d.id: d for d in (await session.execute(select(Drawing).where(Drawing.id.in_(drawing_ids)))).scalars().all()}
    return [tree_item(d, threshold, drawings) for d in docs], int(total)


@dataclass(slots=True)
class FilterPage:
    ids: list[UUID]
    next_cursor: str | None
    matched: int


def _cursor_of(doc_row) -> str:
    return f"{doc_row.created_at.isoformat()}|{doc_row.id}"


async def filter_ids(
    session: AsyncSession, project_id: UUID, f: DocFilter, *, limit: int, cursor: str | None = None
) -> tuple[list[UUID], str | None, int]:
    """The next `limit` document ids matching `f` after `cursor` (created_at|id keyset), the cursor to continue
    from (None when this was the last page) and how many documents match in total. Used by the filter-based bulk
    actions, which repeat until the cursor runs out, so a failure never makes them loop on the same rows."""
    from datetime import datetime

    threshold = await get_auto_accept_min(session)
    total = (await session.execute(apply_filter(_base_select(func.count()), project_id, f, threshold))).scalar_one()
    stmt = apply_filter(_base_select(ProjectDocument.id, ProjectDocument.created_at), project_id, f, threshold)
    if cursor:
        created_raw, id_raw = cursor.split("|", 1)
        created, last_id = datetime.fromisoformat(created_raw), UUID(id_raw)
        stmt = stmt.where(
            or_(ProjectDocument.created_at > created, and_(ProjectDocument.created_at == created, ProjectDocument.id > last_id))
        )
    rows = (await session.execute(stmt.order_by(ProjectDocument.created_at, ProjectDocument.id).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _cursor_of(rows[-1]) if more and rows else None
    return [r.id for r in rows], next_cursor, int(total)


# ----------------------------------------------------------------------------- the summary
async def build_summary(session: AsyncSession, project_id: UUID, *, ai_available: bool, ai_message: str | None) -> TreeOut:
    threshold = await get_auto_accept_min(session)
    display = display_status_expr(threshold).label("display")
    live = and_(ProjectDocument.project_id == project_id, ProjectDocument.status != DocStatus.ARCHIVE.value)

    by_status: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    for status, doc_class, n in (
        await session.execute(
            select(display, ProjectDocument.doc_class, func.count())
            .select_from(ProjectDocument)
            .outerjoin(Drawing, Drawing.id == _drawing_join_id())
            .where(live)
            .group_by(display, ProjectDocument.doc_class)
        )
    ).all():
        by_status[status] += n
        if doc_class and status not in ("excluded", "uploading"):
            by_class[doc_class] += n
    pending_upload = by_status.pop("uploading", 0)

    # The groups of the "by document type" view: class -> (drawings) discipline -> drawing type.
    dtype = ProjectDocument.doc_metadata["drawing_type"].astext
    is_drawing = ProjectDocument.doc_class == DocClass.DRAWING.value
    discipline = case((is_drawing, ProjectDocument.sub_type), else_=None).label("discipline")
    drawing_type = case((is_drawing, dtype), else_=None).label("drawing_type")
    groups = [
        GroupCount(doc_class=c, discipline=disc, drawing_type=dt, count=n)
        for c, disc, dt, n in (
            await session.execute(
                select(ProjectDocument.doc_class, discipline, drawing_type, func.count())
                .where(live, ProjectDocument.status != DocStatus.PENDING_UPLOAD.value)
                .group_by(ProjectDocument.doc_class, discipline, drawing_type)
            )
        ).all()
    ]

    folder = _folder().label("folder")
    folders = [
        FolderCount(folder=fd, count=n)
        for fd, n in (
            await session.execute(
                select(folder, func.count())
                .where(live, ProjectDocument.status != DocStatus.PENDING_UPLOAD.value)
                .group_by(folder)
                .order_by(folder)
                .limit(MAX_FOLDERS)
            )
        ).all()
    ]

    drawings_total = drawings_ready = 0
    for status, n in (
        await session.execute(
            select(display, func.count())
            .select_from(ProjectDocument)
            .outerjoin(Drawing, Drawing.id == _drawing_join_id())
            .where(live, ProjectDocument.routed_kind == "drawing")
            .group_by(display)
        )
    ).all():
        drawings_total += n
        drawings_ready += n if status == "ready" else 0
    first_drawing = (
        await session.execute(
            select(ProjectDocument.routed_ref["drawing_id"].astext)
            .select_from(ProjectDocument)
            .outerjoin(Drawing, Drawing.id == _drawing_join_id())
            .where(live, ProjectDocument.routed_kind == "drawing", display == "ready")
            .order_by(func.coalesce(ProjectDocument.document_number, ProjectDocument.original_filename), ProjectDocument.id)
            .limit(1)
        )
    ).scalar_one_or_none()

    boq_rows = (
        await session.execute(
            select(ProjectDocument.id, ProjectDocument.original_filename)
            .where(
                live, ProjectDocument.doc_class == DocClass.BOQ.value, ProjectDocument.routed_kind == "boq_wizard",
                ProjectDocument.routed_ref["importable"].astext == "true",
            )
            .order_by(ProjectDocument.created_at, ProjectDocument.id)
            .limit(MAX_BOQ_DOCS)
        )
    ).all()

    addenda = (
        await session.execute(select(func.count()).select_from(Addendum).where(Addendum.project_id == project_id, Addendum.withdrawn_at.is_(None)))
    ).scalar_one()

    packages = await package_progress(session, project_id)
    active = {PackageStatus.PROCESSING.value, PackageStatus.UPLOADING.value}
    summary = TreeSummary(
        total=sum(by_status.values()), by_display_status=dict(by_status), by_class=dict(by_class),
        needs_check=by_status.get("needs_check", 0), in_progress=sum(by_status.get(k, 0) for k in IN_PROGRESS),
        pending_upload=pending_upload, drawings_total=drawings_total, drawings_ready=drawings_ready,
        boq_documents=[TreeBoqDoc(id=i, name=n) for i, n in boq_rows], first_drawing_id=UUID(first_drawing) if first_drawing else None,
        addenda=int(addenda), packages_processing=sum(1 for p in packages if p.status in active),
        auto_accept_min=threshold, ai_available=ai_available, ai_message=ai_message,
    )
    return TreeOut(summary=summary, groups=groups, folders=folders, packages=packages)


async def package_progress(session: AsyncSession, project_id: UUID) -> list[PackageProgress]:
    pkgs = (
        await session.execute(select(TenderPackage).where(TenderPackage.project_id == project_id).order_by(TenderPackage.created_at.desc()).limit(20))
    ).scalars().all()
    if not pkgs:
        return []
    counts: dict[UUID, Counter[str]] = {p.id: Counter() for p in pkgs}
    for pid, status, n in (
        await session.execute(
            select(ProjectDocument.package_id, ProjectDocument.status, func.count())
            .where(ProjectDocument.package_id.in_(list(counts)), ProjectDocument.parent_document_id.is_(None))
            .group_by(ProjectDocument.package_id, ProjectDocument.status)
        )
    ).all():
        counts[pid][status] += n
    out = []
    for p in pkgs:
        c = counts[p.id]
        registered = sum(c.values())
        pending = c.get(DocStatus.PENDING_UPLOAD.value, 0)
        waiting = c.get(DocStatus.RECEIVED.value, 0) + c.get(DocStatus.PROCESSING.value, 0)
        out.append(
            PackageProgress(
                id=p.id, label=p.label, status=p.status, created_at=p.created_at,
                expected_count=p.expected_count if p.expected_count is not None else registered,
                registered=registered, uploaded=registered - pending, waiting=waiting, pending_upload=pending,
            )
        )
    return out
