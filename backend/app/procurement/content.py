"""Shared data shape for RFQ content generation (email body + pricing sheet).

Deliberately carries ONLY the four fields the SRS allows a vendor to see
(item_no, description, unit, quantity) -- see docs/procurement-rfq.md's
"content boundary" section and
tests/unit/test_procurement_content_boundary.py. Never add a rate/cost/
budget field here, and never pass app.models.boq.BoqLineItem or
app.models.costlib.* objects directly into rendering/pricing_sheet -- build
this dataclass from them instead so the boundary is enforced by the type,
not by call-site discipline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RfqLineItem:
    boq_line_item_id: uuid.UUID
    item_no: str
    description: str
    uom: str | None
    quantity: float | None
