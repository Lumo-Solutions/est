"""A confirmed PDF BOQ is routed to the BOQ import wizard (its PDF flow); other file types still are not."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import ConflictError
from app.services.tender_intake import _route_boq


def _doc(ext: str):
    return SimpleNamespace(ext=ext, doc_metadata={}, routed_kind=None, routed_ref=None)


@pytest.mark.parametrize("ext,importable", [("xlsx", True), ("csv", True), ("pdf", True), ("xls", False)])
async def test_boq_routes_to_the_wizard(ext, importable):
    doc = _doc(ext)
    await _route_boq(None, None, doc)
    assert doc.routed_kind == "boq_wizard" and doc.routed_ref["importable"] is importable


async def test_other_types_are_still_refused():
    with pytest.raises(ConflictError):
        await _route_boq(None, None, _doc("docx"))
