"""Per-file safety for tender intake. Extends the C2 attachment layer
(app/procurement/attachment_safety.py) with the tender allow-list: dxf, dwg,
docx, doc, xls and zip on top of pdf/xlsx/csv/jpg/png. Pure and synchronous
(bytes in, result out); the worker calls it under its time limits.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.enums import AttachmentSafetyStatus as S
from app.procurement.attachment_safety import _ZIP_MAGIC, _OLE_MAGIC, _PDF_MAGIC, _PNG_MAGIC, _JPEG_MAGIC, _has_macro

ALLOWED_EXTENSIONS = {"pdf", "dxf", "dwg", "xlsx", "xls", "csv", "docx", "doc", "jpg", "jpeg", "png", "zip"}
# Macro-enabled or otherwise executable-adjacent containers: rejected by name.
MACRO_EXTENSIONS = {"xlsm", "docm", "xlsb", "pptm", "xltm", "dotm"}

_DXF_HEAD_MARKERS = (b"SECTION", b"AutoCAD Binary DXF")


@dataclass(frozen=True, slots=True)
class IntakeSafety:
    status: str
    sniffed: str | None
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == S.ACCEPTED.value

    @property
    def is_archive(self) -> bool:
        return self.accepted and self.sniffed == "zip"


def extension_of(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def sniff(data: bytes) -> str | None:
    """Magic-byte sniff. Unlike C2's, ASCII DXF is recognised before the csv fallback."""
    head = data[:16]
    if head.startswith(_PDF_MAGIC):
        return "pdf"
    if head.startswith(_PNG_MAGIC):
        return "png"
    if head.startswith(_JPEG_MAGIC):
        return "jpeg"
    if head.startswith(_ZIP_MAGIC):
        return "zip"
    if head.startswith(_OLE_MAGIC):
        return "ole"
    if head[:4] == b"AC10" or head[:6] in (b"AC1009", b"AC1012", b"AC1014", b"AC1015", b"AC1018", b"AC1021", b"AC1024", b"AC1027", b"AC1032"):
        return "dwg"
    top = data[:4096]
    if b"\x00" not in top and any(marker in top for marker in _DXF_HEAD_MARKERS) and b"SECTION" in top:
        return "dxf"
    if top.startswith(b"AutoCAD Binary DXF"):
        return "dxf"
    try:
        top.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "csv"


def _zip_content_types(data: bytes) -> bytes | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("[Content_Types].xml")
    except (zipfile.BadZipFile, KeyError):
        return None


def _reject(status: S, sniffed: str | None, reason: str) -> IntakeSafety:
    return IntakeSafety(status.value, sniffed, reason)


def check_file(*, filename: str, data: bytes, settings: Settings) -> IntakeSafety:
    if len(data) > settings.intake_max_file_size_bytes:
        return _reject(S.REJECTED_SIZE, None, "file exceeds the intake size limit")

    ext = extension_of(filename)
    if ext in MACRO_EXTENSIONS:
        return _reject(S.REJECTED_MACRO, None, f"macro-enabled format .{ext} is not accepted")
    if ext not in ALLOWED_EXTENSIONS:
        return _reject(S.REJECTED_TYPE, None, f"extension {ext!r} not allow-listed")

    sniffed = sniff(data)

    if ext in ("xlsx", "docx"):
        if sniffed == "ole":
            return _reject(S.REJECTED_ENCRYPTED, sniffed, "password-protected Office document")
        if sniffed != "zip":
            return _reject(S.REJECTED_TYPE, sniffed, f"declared .{ext} but content is not an Office zip")
        marker = b"spreadsheetml" if ext == "xlsx" else b"wordprocessingml"
        types = _zip_content_types(data)
        if types is None or marker not in types:
            return _reject(S.REJECTED_TYPE, sniffed, f"zip is not a valid .{ext}")
        if _has_macro(data):
            return _reject(S.REJECTED_MACRO, sniffed, "document contains a macro (vbaProject.bin)")
        return IntakeSafety(S.ACCEPTED.value, ext)

    if ext in ("xls", "doc"):
        if sniffed != "ole":
            return _reject(S.REJECTED_TYPE, sniffed, f"declared .{ext} but content is not a legacy Office file")
        return IntakeSafety(S.ACCEPTED.value, "ole")

    if ext == "zip":
        if sniffed != "zip":
            return _reject(S.REJECTED_TYPE, sniffed, "declared .zip but content is not a zip archive")
        return IntakeSafety(S.ACCEPTED.value, "zip")

    if ext == "pdf":
        if sniffed != "pdf":
            return _reject(S.REJECTED_TYPE, sniffed, "declared .pdf but content is not a PDF")
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return _reject(S.REJECTED_ENCRYPTED, sniffed, "PDF is password-protected")
            pages = len(reader.pages)
        except (PdfReadError, ValueError) as exc:
            return _reject(S.REJECTED_TYPE, sniffed, f"could not parse PDF: {exc}")
        if pages > settings.intake_max_pdf_pages:
            return _reject(S.REJECTED_PAGE_LIMIT, sniffed, f"PDF has {pages} pages (limit {settings.intake_max_pdf_pages})")
        return IntakeSafety(S.ACCEPTED.value, "pdf")

    if ext == "dxf":
        if sniffed != "dxf":
            return _reject(S.REJECTED_TYPE, sniffed, "declared .dxf but content is not a DXF")
        return IntakeSafety(S.ACCEPTED.value, "dxf")

    if ext == "dwg":
        if sniffed != "dwg":
            return _reject(S.REJECTED_TYPE, sniffed, "declared .dwg but content is not a DWG")
        return IntakeSafety(S.ACCEPTED.value, "dwg")

    if ext in ("jpg", "jpeg", "png"):
        if sniffed not in ("jpeg", "png"):
            return _reject(S.REJECTED_TYPE, sniffed, f"declared .{ext} but content is not an image")
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
        except Exception as exc:  # noqa: BLE001 -- any decode failure (incl. decompression bomb) is a rejection
            return _reject(S.REJECTED_TYPE, sniffed, f"could not decode image: {exc}")
        return IntakeSafety(S.ACCEPTED.value, sniffed)

    if ext == "csv":
        if b"\x00" in data:
            return _reject(S.REJECTED_TYPE, sniffed, "declared .csv but content contains binary data")
        return IntakeSafety(S.ACCEPTED.value, "csv")

    return _reject(S.REJECTED_TYPE, sniffed, "content does not match any allow-listed type")
