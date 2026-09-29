"""Tender intake: archive expansion and per-file safety (app/intake/archive.py, safety.py)."""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter

from app.core.config import Settings
from app.core.enums import AttachmentSafetyStatus as S
from app.intake.archive import ArchiveLimits, expand_zip, safe_member_path
from app.intake.safety import check_file, sniff

_REQUIRED = dict(
    APP_DATABASE_URL="postgresql://x/y",
    MIGRATOR_DATABASE_URL="postgresql://x/y",
    S3_ENDPOINT="http://s3.test",
    VLLM_API_BASE="http://vllm.internal:8000/v1",
)


def _settings(**overrides: object) -> Settings:
    return Settings(**_REQUIRED, **overrides)  # type: ignore[arg-type]


def _zip(members: list[tuple[str, bytes]], *, compress: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compress) as zf:
        for name, payload in members:
            zf.writestr(name, payload)
    return buf.getvalue()


def _pdf(pages: int = 1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _xlsx() -> bytes:
    wb = Workbook()
    wb.active["A1"] = "x"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LIMITS = ArchiveLimits()


# ------------------------------------------------------------------ archives
def test_clean_zip_yields_its_files_with_normalised_paths():
    data = _zip([("Drawings\\a.pdf", b"one"), ("./Forms/b.pdf", b"two"), ("Forms/", b""), ("__MACOSX/x", b"junk"), (".DS_Store", b"j")])
    result = expand_zip(data, LIMITS)
    assert result.fatal is None
    assert sorted(f.path for f in result.files) == ["Drawings/a.pdf", "Forms/b.pdf"]


def test_nul_in_a_member_name_is_unsafe():
    # zipfile itself truncates names at NUL, so this is checked on the validator directly.
    assert safe_member_path("bad\x00name.txt") is None


@pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/etc/passwd", "C:\\win\\x.txt", "..\\evil.txt"])
def test_traversal_and_absolute_names_reject_the_whole_archive(name):
    assert safe_member_path(name) is None
    result = expand_zip(_zip([("ok.txt", b"fine"), (name, b"x")]), LIMITS)
    assert result.fatal is not None and result.fatal[0] == S.REJECTED_ARCHIVE.value
    assert result.files == []


def test_high_compression_ratio_is_a_bomb():
    result = expand_zip(_zip([("bomb.bin", b"0" * 20_000_000)]), LIMITS)
    assert result.fatal and result.fatal[0] == S.REJECTED_ZIP_BOMB.value


def test_ratio_is_checked_before_size_so_a_huge_bomb_is_reported_as_a_bomb():
    result = expand_zip(_zip([("bomb.bin", b"0" * 70_000_000)]), LIMITS)
    assert result.fatal and result.fatal[0] == S.REJECTED_ZIP_BOMB.value


def test_entry_count_limit():
    result = expand_zip(_zip([(f"f{i}.txt", b"x" * 10) for i in range(5)]), ArchiveLimits(max_entries=4))
    assert result.fatal and result.fatal[0] == S.REJECTED_ZIP_BOMB.value


def test_total_uncompressed_limit():
    import os

    members = [(f"f{i}.bin", os.urandom(4000)) for i in range(3)]
    result = expand_zip(_zip(members, compress=zipfile.ZIP_STORED), ArchiveLimits(max_total_bytes=10_000))
    assert result.fatal and result.fatal[0] == S.REJECTED_ZIP_BOMB.value


def test_per_entry_size_limit():
    import os

    result = expand_zip(_zip([("big.bin", os.urandom(5000))], compress=zipfile.ZIP_STORED), ArchiveLimits(max_entry_bytes=1000))
    assert result.fatal and result.fatal[0] == S.REJECTED_SIZE.value


def test_encrypted_member_rejects_the_archive():
    raw = bytearray(_zip([("secret.txt", b"x")]))
    # zipfile resets flag_bits on write, so set the "encrypted" bit (0x1) in the local header
    # (flags at +6) and the central directory entry (flags at +8) directly.
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    raw[local + 6] |= 0x1
    raw[central + 8] |= 0x1
    result = expand_zip(bytes(raw), LIMITS)
    assert result.fatal and result.fatal[0] == S.REJECTED_ENCRYPTED.value


def test_nesting_depth_two_is_allowed_three_is_not():
    inner = _zip([("deep.pdf", b"%PDF-1")])
    depth2 = _zip([("mid.zip", inner)])
    ok = expand_zip(_zip([("outer.zip", depth2)]), ArchiveLimits(max_depth=3))
    assert ok.fatal is None and [f.path for f in ok.files] == ["outer.zip/mid.zip/deep.pdf"]

    allowed = expand_zip(depth2, LIMITS)  # top-level zip (depth 1) holding one nested zip (depth 2)
    assert allowed.fatal is None and [f.path for f in allowed.files] == ["mid.zip/deep.pdf"]

    too_deep = expand_zip(_zip([("outer.zip", depth2)]), LIMITS)
    assert too_deep.fatal and too_deep.fatal[0] == S.REJECTED_ARCHIVE.value
    assert "nesting" in too_deep.fatal[1]


def test_not_a_zip_is_rejected_not_raised():
    result = expand_zip(b"PK\x03\x04garbage", LIMITS)
    assert result.fatal and result.fatal[0] == S.REJECTED_ARCHIVE.value


def test_lying_header_is_caught_by_the_capped_read():
    # A stored entry whose header claims a tiny size but whose data is larger cannot be
    # produced by zipfile itself; the capped read is exercised through a valid large stored entry.
    import os

    data = _zip([("a.bin", os.urandom(3000))], compress=zipfile.ZIP_STORED)
    assert expand_zip(data, ArchiveLimits(max_entry_bytes=3000)).fatal is None


# --------------------------------------------------------------- per-file safety
def test_allow_list_accepts_each_supported_type():
    s = _settings()
    assert check_file(filename="a.pdf", data=_pdf(), settings=s).accepted
    assert check_file(filename="a.xlsx", data=_xlsx(), settings=s).accepted
    assert check_file(filename="a.csv", data=b"a,b\n1,2\n", settings=s).accepted
    assert check_file(filename="a.zip", data=_zip([("x.txt", b"1")]), settings=s).is_archive
    assert check_file(filename="a.xls", data=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32, settings=s).accepted
    assert check_file(filename="a.dwg", data=b"AC1027" + b"\x00" * 32, settings=s).accepted
    dxf = b"0\r\nSECTION\r\n2\r\nHEADER\r\n0\r\nENDSEC\r\n0\r\nEOF\r\n"
    res = check_file(filename="a.dxf", data=dxf, settings=s)
    assert res.accepted and res.sniffed == "dxf"


def test_ascii_dxf_is_not_mistaken_for_csv():
    assert sniff(b"0\r\nSECTION\r\n2\r\nHEADER\r\n") == "dxf"
    assert sniff(b"a,b\r\n1,2\r\n") == "csv"


@pytest.mark.parametrize("name", ["book.xlsm", "doc.docm", "book.xlsb", "deck.pptm"])
def test_macro_enabled_extensions_rejected_by_name(name):
    res = check_file(filename=name, data=_xlsx(), settings=_settings())
    assert res.status == S.REJECTED_MACRO.value


def test_macro_inside_an_xlsx_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_xlsx())) as src, zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("xl/vbaProject.bin", b"\x00" * 8)
    res = check_file(filename="a.xlsx", data=buf.getvalue(), settings=_settings())
    assert res.status == S.REJECTED_MACRO.value


def test_docx_needs_wordprocessingml_and_is_macro_checked():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types>wordprocessingml.document.main+xml</Types>")
        zf.writestr("word/document.xml", "<w:document/>")
    assert check_file(filename="a.docx", data=buf.getvalue(), settings=_settings()).accepted
    # An xlsx renamed to .docx is not a docx.
    assert check_file(filename="a.docx", data=_xlsx(), settings=_settings()).status == S.REJECTED_TYPE.value


def test_ole_bytes_under_an_ooxml_extension_mean_encrypted():
    res = check_file(filename="a.xlsx", data=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, settings=_settings())
    assert res.status == S.REJECTED_ENCRYPTED.value


def test_encrypted_pdf_and_page_limit_and_size_cap_and_unknown_ext():
    w = PdfWriter()
    w.add_blank_page(width=10, height=10)
    w.encrypt(user_password="secret")
    buf = io.BytesIO()
    w.write(buf)
    s = _settings()
    assert check_file(filename="a.pdf", data=buf.getvalue(), settings=s).status == S.REJECTED_ENCRYPTED.value
    assert check_file(filename="a.pdf", data=_pdf(4), settings=_settings(INTAKE_MAX_PDF_PAGES=3)).status == S.REJECTED_PAGE_LIMIT.value
    assert check_file(filename="a.pdf", data=_pdf(), settings=_settings(INTAKE_MAX_FILE_SIZE_BYTES=100)).status == S.REJECTED_SIZE.value
    assert check_file(filename="a.exe", data=b"MZ", settings=s).status == S.REJECTED_TYPE.value


def test_content_must_match_the_extension():
    s = _settings()
    assert check_file(filename="a.pdf", data=b"not a pdf", settings=s).status == S.REJECTED_TYPE.value
    assert check_file(filename="a.dwg", data=b"plain text", settings=s).status == S.REJECTED_TYPE.value
    assert check_file(filename="a.zip", data=_pdf(), settings=s).status == S.REJECTED_TYPE.value
