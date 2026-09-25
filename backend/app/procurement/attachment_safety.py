"""Attachment allow-list, size/page limits, and malicious-file rejection for
inbound vendor quotations -- untrusted input from the internet.

Every check here runs in a Celery worker (app/workers/tasks/quotation_ingestion.py),
never the FastAPI web process, and never on the poller's own event loop --
see that module's `process_attachment` task and its `soft_time_limit`, which
is the timeout backstop this module deliberately doesn't try to reimplement.

Detection is by content-sniffed magic bytes, not by trusting the declared
filename extension -- a `.pdf` that's actually a zip is rejected as a type
mismatch, not parsed as whatever its extension claims.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.enums import AttachmentSafetyStatus

ALLOWED_EXTENSIONS = {"xlsx", "csv", "pdf", "jpg", "jpeg", "png"}

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_ZIP_MAGIC = b"PK\x03\x04"
# Legacy OLE compound-file signature: how Excel wraps a password-protected
# .xlsx (and the format of the pre-2007 .xls binary format, which is also
# not on the allow-list). Any file with this signature is refused outright,
# regardless of its declared extension.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Zip-bomb guard thresholds (SRS change: reject/quarantine zip bombs before
# ever handing bytes to openpyxl). Deliberately generous for a genuine
# pricing-sheet-sized workbook (a few hundred KB uncompressed) while still
# catching the classic "42.zip"-style ratio bomb.
_MAX_ZIP_ENTRIES = 2_000
_MAX_ZIP_UNCOMPRESSED_TOTAL = 200 * 1024 * 1024
_MAX_ZIP_SINGLE_ENTRY_UNCOMPRESSED = 100 * 1024 * 1024
_MAX_ZIP_COMPRESSION_RATIO = 100


@dataclass(frozen=True, slots=True)
class AttachmentSafetyResult:
    status: str
    sniffed_content_type: str | None
    reason: str | None = None


def _sniff(data: bytes) -> str | None:
    if data.startswith(_PDF_MAGIC):
        return "pdf"
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    if data.startswith(_ZIP_MAGIC):
        return "zip"
    if data.startswith(_OLE_MAGIC):
        return "ole"
    try:
        data.decode("utf-8")
        return "csv"
    except UnicodeDecodeError:
        return None


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _check_zip_bomb(data: bytes) -> str | None:
    """Returns a rejection reason, or None if the zip looks safe to open."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                return f"zip has {len(infos)} entries (limit {_MAX_ZIP_ENTRIES})"
            total_uncompressed = 0
            for info in infos:
                if info.file_size > _MAX_ZIP_SINGLE_ENTRY_UNCOMPRESSED:
                    return f"zip entry {info.filename!r} uncompressed size exceeds limit"
                if info.compress_size > 0 and info.file_size / info.compress_size > _MAX_ZIP_COMPRESSION_RATIO:
                    return f"zip entry {info.filename!r} compression ratio exceeds limit"
                total_uncompressed += info.file_size
            if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_TOTAL:
                return "zip total uncompressed size exceeds limit"
    except zipfile.BadZipFile:
        return "not a valid zip archive"
    return None


def _has_macro(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return any(name.lower().endswith("vbaproject.bin") for name in zf.namelist())
    except zipfile.BadZipFile:
        return False


def _looks_like_xlsx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content_types = zf.read("[Content_Types].xml")
    except (zipfile.BadZipFile, KeyError):
        return False
    return b"spreadsheetml" in content_types


def check_attachment(*, filename: str, data: bytes, settings: Settings) -> AttachmentSafetyResult:
    if len(data) > settings.quotation_max_attachment_size_bytes:
        return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_SIZE.value, None, "attachment exceeds size limit")

    extension = _extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, None, f"extension {extension!r} not allow-listed")

    sniffed = _sniff(data)

    if sniffed == "ole":
        return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_ENCRYPTED.value, sniffed, "password-protected or legacy binary Office format")

    if sniffed == "zip":
        bomb_reason = _check_zip_bomb(data)
        if bomb_reason:
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_ZIP_BOMB.value, sniffed, bomb_reason)
        if extension != "xlsx" or not _looks_like_xlsx(data):
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, "zip archive is not a valid .xlsx workbook")
        if _has_macro(data):
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_MACRO.value, sniffed, "workbook contains a macro (vbaProject.bin)")
        return AttachmentSafetyResult(AttachmentSafetyStatus.ACCEPTED.value, "xlsx")

    if extension == "xlsx":
        return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, "declared .xlsx but content is not a zip archive")

    if sniffed == "pdf":
        if extension != "pdf":
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, f"declared .{extension} but content is a PDF")
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_ENCRYPTED.value, sniffed, "PDF is password-protected")
            page_count = len(reader.pages)
        except (PdfReadError, ValueError) as exc:
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, f"could not parse PDF: {exc}")
        if page_count > settings.quotation_max_pdf_pages:
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_PAGE_LIMIT.value, sniffed, f"PDF has {page_count} pages (limit {settings.quotation_max_pdf_pages})")
        return AttachmentSafetyResult(AttachmentSafetyStatus.ACCEPTED.value, sniffed)

    if sniffed in ("jpeg", "png"):
        if extension not in ("jpg", "jpeg", "png"):
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, f"declared .{extension} but content is a {sniffed} image")
        try:
            # Pillow's built-in Image.MAX_IMAGE_PIXELS guard raises
            # DecompressionBombError for an image whose *decoded* pixel count
            # would be absurd relative to its compressed size -- the image
            # equivalent of the zip-bomb ratio check above.
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
        except Exception as exc:  # noqa: BLE001 -- any decode failure is a rejection, not a crash
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, f"could not decode image: {exc}")
        return AttachmentSafetyResult(AttachmentSafetyStatus.ACCEPTED.value, sniffed)

    if sniffed == "csv" and extension == "csv":
        if b"\x00" in data:
            return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, "declared .csv but content contains binary data")
        return AttachmentSafetyResult(AttachmentSafetyStatus.ACCEPTED.value, sniffed)

    return AttachmentSafetyResult(AttachmentSafetyStatus.REJECTED_TYPE.value, sniffed, "content does not match any allow-listed type")
