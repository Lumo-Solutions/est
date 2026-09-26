from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.boq.import_parser import BoqImportColumnMapping, BoqImportResult, parse_boq_file
from app.core.context import RequestContext
from app.core.errors import ValidationAppError
from app.integrations.s3 import put_object_streaming
from app.models.boq import BoqImportBatch, BoqLineItem
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services.projects import assert_can_see_project

_XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def preview_import(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, data: bytes, filename: str,
    mapping: BoqImportColumnMapping,
) -> BoqImportResult:
    await assert_can_see_project(session, ctx, project_id)
    return parse_boq_file(data, filename, mapping)


async def commit_import(
    session: AsyncSession, ctx: RequestContext, project_id: UUID, data: bytes, filename: str,
    mapping: BoqImportColumnMapping,
) -> list[BoqLineItem]:
    """Re-parses and re-validates (never trusts a client-supplied "this was
    already previewed, just create it" claim) then creates every row in
    the request's single transaction -- if anything fails partway through
    (a race against another concurrent write, an unexpected DB error), the
    request's own transaction rollback (see app/db/session.py::
    get_session()) takes the whole import down with it, not a partial
    tree."""
    await assert_can_see_project(session, ctx, project_id)
    result = parse_boq_file(data, filename, mapping)
    if result.error_count:
        raise ValidationAppError(
            f"BOQ import has {result.error_count} row error(s) -- fix them and re-preview before committing.",
            errors=[{"row_number": r.row_number, "errors": r.errors} for r in result.rows if r.errors],
        )

    # Module D2: retain the original workbook (S3) and the column mapping
    # so a later settlement export can write settled rates back into the
    # exact original cells (D3). .xlsx only -- "write into the client's
    # original Excel workbook" doesn't apply to a .csv import, which gets
    # source_object_key=NULL, same as any import predating this feature.
    # The batch id is generated up front (rather than left to the DB
    # default) purely so the S3 key can embed it in one PUT, with no
    # placeholder-then-rename dance.
    batch_id = uuid4()
    source_object_key: str | None = None
    source_sha256: str | None = None
    sheet_name: str | None = None
    if filename.lower().endswith(".xlsx"):
        source_object_key = f"boq-imports/{project_id}/{batch_id}.xlsx"
        source_sha256 = await put_object_streaming(source_object_key, data, _XLSX_CONTENT_TYPE)
        # Module D3 needs to know which sheet to write settled rates back
        # into for a multi-sheet workbook -- same file already in memory,
        # no extra S3 round trip.
        import io

        from openpyxl import load_workbook

        sheet_name = load_workbook(io.BytesIO(data), read_only=True).active.title

    batch = BoqImportBatch(
        id=batch_id, tenant_id=ctx.tenant_id, project_id=project_id, source_filename=filename,
        source_object_key=source_object_key, source_sha256=source_sha256, sheet_name=sheet_name,
        header_row=mapping.header_row, item_no_column=mapping.item_no_column,
        description_column=mapping.description_column, uom_column=mapping.uom_column,
        quantity_column=mapping.quantity_column, parent_column=mapping.parent_column,
        rate_column=mapping.rate_column, amount_column=mapping.amount_column,
        imported_by=ctx.user_id, imported_at=datetime.now(timezone.utc),
    )
    session.add(batch)
    await session.flush()

    # Topological (layer-by-layer) creation: a row's parent must already
    # exist as a real DB row (with a real id) before create_line_item can
    # reference it as parent_id -- rows with no parent create first, then
    # each pass creates whatever's left whose parent was just created.
    created_by_item_no: dict[str, BoqLineItem] = {}
    created: list[BoqLineItem] = []
    remaining = list(result.rows)
    while remaining:
        still_remaining = []
        progressed = False
        for row in remaining:
            parent = created_by_item_no.get(row.parent_item_no) if row.parent_item_no else None
            if row.parent_item_no is not None and parent is None:
                still_remaining.append(row)
                continue
            assert row.item_no is not None and row.description is not None  # guaranteed by error_count == 0 above
            item = await boq_service.create_line_item(
                session, ctx, project_id,
                BoqLineItemCreate(
                    parent_id=parent.id if parent else None, item_no=row.item_no, description=row.description,
                    uom=row.uom, boq_quantity=row.boq_quantity,
                ),
            )
            item.import_batch_id = batch.id
            # row.row_number is 1-indexed relative to the DATA rows (see
            # app/boq/import_parser.py::ParsedBoqRow) -- convert to the
            # actual spreadsheet row so D3 can address the exact cell
            # (mapping.header_row + 1 is the first data row).
            item.source_row_number = mapping.header_row + row.row_number
            created_by_item_no[row.item_no] = item
            created.append(item)
            progressed = True
        if not progressed:
            # _validate_hierarchy() (app/boq/import_parser.py) already
            # rejects unresolvable/cyclic parent references before
            # error_count could be 0 -- this should be unreachable.
            raise ValidationAppError("BOQ import hierarchy could not be fully resolved")
        remaining = still_remaining

    await session.flush()
    return created
