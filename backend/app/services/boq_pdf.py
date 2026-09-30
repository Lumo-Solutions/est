"""PDF BOQ extraction lifecycle: upload -> (worker) read -> edit rows -> commit.

Rows live as editable JSON on ``boq_pdf_extractions`` until the estimator
commits them; ``boq_line_items`` is untouched before that. The commit goes
through the same parser/validator and tree builder as an xlsx import, so a PDF
BOQ cannot create anything an xlsx import could not. AI-read rows keep their
``ai_read`` flag, page and region on the line item.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.boq.import_parser import BoqImportResult, parse_boq_rows
from app.boq.import_parser import BoqImportColumnMapping
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.enums import AuditAction
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.integrations.s3 import get_object_bytes, presign_get_url, put_object_streaming
from app.models.boq import BoqImportBatch, BoqLineItem, BoqPdfExtraction
from app.services import audit
from app.services.boq_import import create_items_tree
from app.services.projects import assert_can_see_project
from app.services.tender_intake_processing import bucket_for

MAX_PDF_BYTES = 60 * 1024 * 1024
_MAPPING = BoqImportColumnMapping(
    item_no_column="item_no", description_column="description", uom_column="uom", quantity_column="quantity"
)
EDITABLE_FIELDS = ("item_no", "description", "uom", "quantity")


def object_key(tenant_id: UUID, sha256: str) -> str:
    return f"boq-pdf/{tenant_id}/{sha256}.pdf"


# ------------------------------------------------------------------ rows

def rows_to_json(pdf_rows: list[Any]) -> list[dict]:
    out = []
    for r in pdf_rows:
        out.append(
            {
                "row_id": str(uuid.uuid4()), "page": r.page, "item_no": r.item_no, "description": r.description,
                "uom": r.uom, "quantity": r.quantity, "bbox": r.bbox, "page_size": r.page_size,
                "source": r.source, "confidence": r.confidence, "edited": False,
            }
        )
    return out


def validate_rows(rows: list[dict]) -> BoqImportResult:
    """Same validation as an xlsx import (item_no/description required, numeric quantity,
    duplicates, parents from dot-numbering). Row i of the result is rows[i]."""
    raw = [
        {
            "item_no": (r.get("item_no") or "").strip(),
            "description": (r.get("description") or "").strip(),
            "uom": (r.get("uom") or "").strip(),
            "quantity": "" if r.get("quantity") in (None, "") else str(r["quantity"]),
        }
        for r in rows
    ]
    return parse_boq_rows(raw, _MAPPING)


def rows_out(rows: list[dict], result: BoqImportResult) -> list[dict]:
    return [{**row, "errors": parsed.errors} for row, parsed in zip(rows, result.rows, strict=True)]


# ------------------------------------------------------------------ lifecycle

async def create_extraction(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, *, data: bytes, filename: str,
    use_ai: bool = True, document_id: UUID | None = None,
) -> BoqPdfExtraction:
    await assert_can_see_project(session, ctx, project_id)
    if not data.startswith(b"%PDF"):
        raise ValidationAppError("That file is not a PDF")
    if len(data) > MAX_PDF_BYTES:
        raise ValidationAppError(f"PDF is larger than the {MAX_PDF_BYTES // (1024 * 1024)} MiB limit")
    settings = get_settings()
    sha = hashlib.sha256(data).hexdigest()
    key = object_key(ctx.tenant_id, sha)
    stored = await put_object_streaming(key, data, "application/pdf", bucket=bucket_for(settings))
    if stored != sha:
        raise ConflictError("Stored object checksum did not match the upload")
    row = BoqPdfExtraction(
        tenant_id=ctx.tenant_id, project_id=project_id, document_id=document_id, source_filename=filename[:512],
        bucket=bucket_for(settings), object_key=key, sha256=sha, status="queued", use_ai=use_ai,
        created_by=ctx.user_id, updated_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.IMPORT, entity_type="boq_pdf_extraction", entity_id=row.id,
        project_id=project_id, payload={"event": "upload", "filename": filename, "use_ai": use_ai, "sha256": sha},
    )
    return row


async def get_extraction(session: AsyncSession, extraction_id: UUID) -> BoqPdfExtraction:
    row = (await session.execute(select(BoqPdfExtraction).where(BoqPdfExtraction.id == extraction_id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"BOQ PDF extraction {extraction_id} not found")
    return row


async def list_extractions(session: AsyncSession, project_id: UUID) -> list[BoqPdfExtraction]:
    res = await session.execute(
        select(BoqPdfExtraction).where(BoqPdfExtraction.project_id == project_id).order_by(BoqPdfExtraction.created_at.desc())
    )
    return list(res.scalars().all())


async def run_extraction(session: AsyncSession, ctx: RequestContext, extraction_id: UUID, progress) -> None:
    """Worker body. `progress(done, total, page_summary)` commits in its own session so the UI can
    poll while this transaction is still open."""
    from app.ai.gateway import AIMeta
    from app.boq.pdf_ai import extract_pdf_boq

    # NOTE: no write to the extraction row before the final one. The task claims it ('running') and
    # reports progress from independent committed sessions; a row lock held by this transaction
    # would make those sessions wait on it forever.
    ex = await get_extraction(session, extraction_id)
    data = await get_object_bytes(ex.object_key, bucket=ex.bucket)
    summary: list[dict] = []

    async def on_progress(done: int, total: int, status: str) -> None:
        summary.append({"page": done, "status": status})
        await progress(done, total, list(summary))

    result = await extract_pdf_boq(
        data, meta=AIMeta(project_id=ex.project_id, entity_type="boq_pdf_extraction", entity_id=str(ex.id)),
        use_ai=ex.use_ai, on_progress=on_progress,
    )
    ex.rows = rows_to_json(result.rows)
    ex.page_summary = [
        {"page": p.page, "status": p.status, "note": p.note, "rows": len(p.rows), "quality": round(p.quality, 3)}
        for p in result.pages
    ]
    ex.pages_total = len(result.pages)
    ex.pages_done = len(result.pages)
    ex.warnings = result.warnings
    ex.status = "ready"
    ex.error = None
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.UPDATE, entity_type="boq_pdf_extraction", entity_id=ex.id,
        project_id=ex.project_id,
        payload={"event": "extracted", "rows": len(ex.rows), "counts": result.counts()},
    )


async def save_rows(session: AsyncSession, ctx: RequestContext, extraction_id: UUID, rows: list[dict]) -> BoqPdfExtraction:
    ex = await get_extraction(session, extraction_id)
    if ex.status not in ("ready",):
        raise ConflictError(f"Cannot edit rows while the extraction is {ex.status}")
    if len(rows) > 20_000:
        raise ValidationAppError("Too many rows")
    before = {r["row_id"]: r for r in ex.rows}
    cleaned: list[dict] = []
    for r in rows:
        rid = r.get("row_id") or str(uuid.uuid4())
        old = before.get(rid)
        new = {
            "row_id": rid,
            "page": r.get("page") or (old or {}).get("page") or 1,
            "item_no": (r.get("item_no") or None),
            "description": (r.get("description") or "").strip(),
            "uom": (r.get("uom") or None),
            "quantity": r.get("quantity"),
            "bbox": (old or {}).get("bbox") or r.get("bbox") or [0, 0, 0, 0],
            "page_size": (old or {}).get("page_size") or r.get("page_size") or [0, 0],
            # provenance is never client-controlled: a new row is a person's ("manual"); an
            # existing row keeps how it was read. Editing an AI row keeps it flagged ai.
            "source": (old or {}).get("source") or "manual",
            "confidence": (old or {}).get("confidence", 1.0),
        }
        new["edited"] = old is None or any(old.get(f) != new.get(f) for f in EDITABLE_FIELDS) or bool(old.get("edited"))
        cleaned.append(new)
    ex.rows = cleaned
    ex.updated_by = ctx.user_id
    await session.flush()
    return ex


async def commit_extraction(session: AsyncSession, ctx: RequestContext, extraction_id: UUID) -> list[BoqLineItem]:
    ex = await get_extraction(session, extraction_id)
    await assert_can_see_project(session, ctx, ex.project_id)
    if ex.status == "committed":
        raise ConflictError("This extraction was already imported")
    if ex.status != "ready":
        raise ConflictError(f"Cannot import while the extraction is {ex.status}")
    result = validate_rows(ex.rows)
    if result.error_count:
        raise ValidationAppError(
            f"BOQ import has {result.error_count} row error(s) -- fix them before importing.",
            errors=[{"row_number": r.row_number, "errors": r.errors} for r in result.rows if r.errors],
        )
    batch = BoqImportBatch(
        id=uuid.uuid4(), tenant_id=ctx.tenant_id, project_id=ex.project_id, source_filename=ex.source_filename,
        source_object_key=None, source_sha256=ex.sha256, sheet_name=None, header_row=1,
        item_no_column="item_no", description_column="description", uom_column="uom", quantity_column="quantity",
        parent_column=None, rate_column=None, amount_column=None, imported_by=ctx.user_id,
        imported_at=datetime.now(timezone.utc),
    )
    session.add(batch)
    await session.flush()
    by_index = {i + 1: row for i, row in enumerate(ex.rows)}

    def annotate(item: BoqLineItem, parsed) -> None:  # noqa: ANN001
        src = by_index[parsed.row_number]
        item.source_kind = "pdf"
        item.source_page = src.get("page")
        item.source_bbox = src.get("bbox")
        item.ai_read = src.get("source") == "ai"

    created = await create_items_tree(session, ctx, ex.project_id, result.rows, batch.id, annotate)
    ex.status = "committed"
    ex.batch_id = batch.id
    ex.committed_at = datetime.now(timezone.utc)
    await session.flush()
    await audit.record(
        session, ctx, action=AuditAction.IMPORT, entity_type="boq_pdf_extraction", entity_id=ex.id,
        project_id=ex.project_id,
        payload={
            "event": "commit", "items": len(created), "ai_read": sum(1 for r in ex.rows if r.get("source") == "ai"),
            "edited": sum(1 for r in ex.rows if r.get("edited")), "batch_id": str(batch.id),
        },
    )
    return created


async def source_url(session: AsyncSession, ctx: RequestContext, ex: BoqPdfExtraction) -> str:
    await audit.record(
        session, ctx, action=AuditAction.DOWNLOAD, entity_type="boq_pdf_extraction", entity_id=ex.id,
        project_id=ex.project_id, payload={"filename": ex.source_filename, "sha256": ex.sha256},
    )
    return await presign_get_url(ex.object_key, bucket=ex.bucket)
