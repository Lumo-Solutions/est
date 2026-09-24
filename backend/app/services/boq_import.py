from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.boq.import_parser import BoqImportColumnMapping, BoqImportResult, parse_boq_file
from app.core.context import RequestContext
from app.core.errors import ValidationAppError
from app.models.boq import BoqLineItem
from app.schemas.boq import BoqLineItemCreate
from app.services import boq as boq_service
from app.services.projects import assert_can_see_project


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
