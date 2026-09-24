from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.procurement.content import RfqLineItem

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@lru_cache
def _env() -> Environment:
    # autoescape is load-bearing, not a default worth relying on implicitly:
    # item descriptions come from a tender BOQ import (arbitrary vendor/
    # client-supplied text) and are rendered straight into an HTML email.
    return Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=select_autoescape(["html.j2"]))


def render_rfq_email(
    *,
    vendor_name: str,
    rfq_ref: str,
    package_name: str,
    items: list[RfqLineItem],
    due_at: str | None,
    sender_name: str,
) -> str:
    """Renders the RFQ email body. See app/procurement/content.py's
    docstring for the content boundary this context must respect -- only
    item_no/description/unit/quantity, the addressed vendor's own name, no
    rates/costs/budgets, no other vendor's name."""
    template = _env().get_template("rfq_email.html.j2")
    return template.render(
        vendor_name=vendor_name,
        rfq_ref=rfq_ref,
        package_name=package_name,
        items=items,
        due_at=due_at,
        sender_name=sender_name,
    )
