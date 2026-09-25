"""Untrusted-attachment safety checks (allow-list, size/page limits,
macro/encrypted/archive/zip-bomb rejection) -- see
app/procurement/attachment_safety.py."""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter

from app.core.config import Settings
from app.core.enums import AttachmentSafetyStatus
from app.procurement.attachment_safety import check_attachment

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)


def _settings(**overrides: object) -> Settings:
    return Settings(**_REQUIRED, **overrides)  # type: ignore[arg-type]


def _valid_xlsx_bytes() -> bytes:
    wb = Workbook()
    wb.active["A1"] = "hello"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _valid_pdf_bytes(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _valid_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color="red").save(buf, format="PNG")
    return buf.getvalue()


def test_accepts_a_genuine_pricing_sheet_xlsx():
    result = check_attachment(filename="quote.xlsx", data=_valid_xlsx_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.ACCEPTED.value


def test_accepts_a_genuine_pdf():
    result = check_attachment(filename="quote.pdf", data=_valid_pdf_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.ACCEPTED.value


def test_accepts_a_genuine_png():
    result = check_attachment(filename="quote.png", data=_valid_png_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.ACCEPTED.value


def test_accepts_a_genuine_csv():
    result = check_attachment(filename="quote.csv", data=b"item,qty,rate\n1.0,100,5.5\n", settings=_settings())
    assert result.status == AttachmentSafetyStatus.ACCEPTED.value


def test_rejects_extension_not_on_allow_list():
    result = check_attachment(filename="quote.docx", data=b"anything", settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_TYPE.value


def test_rejects_xlsm_outright_even_with_no_macro_content():
    """Belt-and-suspenders: .xlsm is never on the allow-list at all,
    regardless of whether it actually contains a vbaProject.bin."""
    result = check_attachment(filename="quote.xlsm", data=_valid_xlsx_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_TYPE.value


def test_rejects_xlsx_containing_a_macro():
    wb = Workbook()
    wb.active["A1"] = "hello"
    buf = io.BytesIO()
    wb.save(buf)
    # Re-zip the saved workbook with an extra vbaProject.bin entry, exactly
    # how a macro-enabled workbook renamed to .xlsx would look on disk.
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            zf.writestr(name, src.read(name))
        zf.writestr("xl/vbaProject.bin", b"fake-macro-bytes")

    result = check_attachment(filename="quote.xlsx", data=out.getvalue(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_MACRO.value


def test_rejects_password_protected_xlsx_by_ole_signature():
    ole_signature = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    result = check_attachment(filename="quote.xlsx", data=ole_signature + b"\x00" * 100, settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_ENCRYPTED.value


def test_rejects_password_protected_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret")
    buf = io.BytesIO()
    writer.write(buf)

    result = check_attachment(filename="quote.pdf", data=buf.getvalue(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_ENCRYPTED.value


def test_rejects_pdf_over_page_limit():
    result = check_attachment(
        filename="quote.pdf", data=_valid_pdf_bytes(pages=5), settings=_settings(QUOTATION_MAX_PDF_PAGES=2)
    )
    assert result.status == AttachmentSafetyStatus.REJECTED_PAGE_LIMIT.value


def test_rejects_oversized_attachment_before_any_parsing():
    result = check_attachment(
        filename="quote.xlsx", data=_valid_xlsx_bytes(), settings=_settings(QUOTATION_MAX_ATTACHMENT_SIZE_BYTES=10)
    )
    assert result.status == AttachmentSafetyStatus.REJECTED_SIZE.value


def test_rejects_zip_bomb_by_compression_ratio():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types xmlns=\"x\"><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/></Types>")
        zf.writestr("bomb.bin", b"0" * 50_000_000)

    result = check_attachment(filename="quote.xlsx", data=out.getvalue(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value


def test_rejects_type_mismatch_between_extension_and_sniffed_content():
    result = check_attachment(filename="quote.csv", data=_valid_pdf_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_TYPE.value


def test_rejects_csv_containing_binary_data():
    result = check_attachment(filename="quote.csv", data=b"item,qty\x00,rate\n", settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_TYPE.value


def test_rejects_image_decompression_bomb(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4)  # our 4x4 test PNG (16px) now looks like a bomb
    result = check_attachment(filename="quote.png", data=_valid_png_bytes(), settings=_settings())
    assert result.status == AttachmentSafetyStatus.REJECTED_TYPE.value
