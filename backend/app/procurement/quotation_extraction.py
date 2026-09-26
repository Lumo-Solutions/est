"""LLM extraction for vendor quotations that aren't our own pricing-sheet
template (PDF, scanned image, or an unrecognized spreadsheet) -- SRS
requirement #3: the vision-LLM only ever extracts into this strict schema,
its output is validated here, and nothing it returns can trigger any action.
There is no field for a BOQ line item id in the schema at all -- matching a
returned row to a BOQ item is a separate deterministic step
(app/procurement/quotation_matching.py), never a model decision.
"""

from __future__ import annotations

import base64

from pydantic import BaseModel, Field

from app.integrations.vllm import extract_json
from app.procurement.prompts import load_schema, render_prompt


class ExtractedLineItem(BaseModel):
    vendor_item_text: str | None = None
    vendor_description_text: str
    unit_price: float | None = None
    quantity: float | None = None
    extended_price_stated: float | None = None
    vendor_uom: str | None = None
    remarks_text: str | None = None


class ExtractedExclusion(BaseModel):
    flag_text: str
    source_quote_text: str
    source_location: str | None = None


class QuotationExtractionResult(BaseModel):
    currency: str | None = None
    vat_inclusive: bool | None = None
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    stated_total: float | None = None
    exclusions: list[ExtractedExclusion] = Field(default_factory=list)
    confidence: float = 0.0


async def extract_quotation(
    *,
    candidate_text: str,
    image_bytes: bytes | None,
    image_mime: str = "image/png",
    page_number: int | None = None,
    page_count: int | None = None,
) -> QuotationExtractionResult:
    """Calls vLLM (real or mock) with the quotation_extraction.j2 prompt,
    constrained to quotation_extraction.schema.json via guided decoding.
    Text-only when image_bytes is None; text+image otherwise. The raw dict
    from extract_json is validated through QuotationExtractionResult before
    any caller sees it -- a guided-JSON response that somehow doesn't match
    the Pydantic shape raises here rather than propagating unchecked data."""
    system_prompt, user_prompt = render_prompt(
        "quotation_extraction.j2",
        candidate_text=candidate_text,
        has_image=image_bytes is not None,
        page_number=page_number,
        page_count=page_count,
    )
    schema = load_schema("quotation_extraction.schema.json")

    image_data_url = None
    if image_bytes is not None:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        image_data_url = f"data:{image_mime};base64,{b64}"

    raw = await extract_json(
        system_prompt=system_prompt, user_prompt=user_prompt, json_schema=schema, image_data_url=image_data_url
    )
    return QuotationExtractionResult.model_validate(raw)
