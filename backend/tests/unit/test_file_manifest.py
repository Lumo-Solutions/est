"""The fast, AI-free manifest read (docs/boq-agent/plan.md section 2): PDFium-only PDF read, sheet info, hints,
partial index, and the rules-only routing gate. No database, no model."""

from __future__ import annotations

from app.intake import sample_pack
from app.intake.extract import extract_content
from app.intake.manifest import PAGE1_TEXT_CHARS, build_entry
from app.intake.rules import classify_rules
from app.services import tender_intake as intake_service


def _entry(name: str, ext: str, data: bytes, folder: str = "Tender/BOQ"):
    content = extract_content(filename=name, ext=ext, sniffed=ext, data=data, fast=True)
    rules = classify_rules(content, name, folder=folder)
    return content, build_entry(
        content=content, rules=rules, filename=name, folder=folder, path=f"{folder}/{name}", size_bytes=len(data), sha256="a" * 64
    )


def test_pdf_fast_read_has_pages_sizes_text_and_hints():
    data = sample_pack._vector_pdf("ARC-101", "B", "Ground floor plan", "A1")
    content, entry = _entry("ARC-101.pdf", "pdf", data, folder="Drawings")
    assert entry.page_count == 1
    assert entry.page_sizes and len(entry.page_sizes[0]) == 2
    assert entry.hints.get("doc_class") == "drawing"
    assert not entry.partial_index
    assert len(entry.page1_text) <= PAGE1_TEXT_CHARS
    assert "ARC-101" in entry.embedding_text()


def test_text_pdf_page1_text_is_captured():
    data = sample_pack._text_pdf(["ADDENDUM NO. 2", "Clarifications to the tender"])
    _, entry = _entry("addendum2.pdf", "pdf", data, folder="Addenda")
    assert "ADDENDUM" in entry.page1_text.upper()
    assert entry.hints.get("doc_class") == "addendum"
    assert entry.hints.get("addendum_number") == "2"


def test_xlsx_sheet_names_header_and_rows():
    _, entry = _entry("boq.xlsx", "xlsx", sample_pack._boq_xlsx())
    assert entry.sheets and entry.sheets[0]["name"]
    assert entry.sheets[0]["rows"] and entry.sheets[0]["rows"] > 1
    assert entry.hints.get("doc_class") == "boq"


def test_unreadable_file_is_partial_not_failed():
    content, entry = _entry("broken.pdf", "pdf", b"%PDF-1.4 not really a pdf")
    assert content.error
    assert entry.partial_index and entry.partial_reason
    assert entry.filename == "broken.pdf"  # still searchable by name


def test_timeout_partial_reason_wins():
    content = extract_content(filename="x.pdf", ext="pdf", sniffed="pdf", data=b"", fast=True)
    entry = build_entry(
        content=content, rules=None, filename="x.pdf", folder="", path="x.pdf", size_bytes=0, sha256="b" * 64,
        partial_reason="reading took longer than 60 s",
    )
    assert entry.partial_index and entry.partial_reason == "reading took longer than 60 s"


def test_dwg_and_image_are_name_and_size_only():
    _, dwg = _entry("plan.dwg", "dwg", b"AC1027" + b"\0" * 64, folder="CAD")
    assert dwg.page1_text == "" and dwg.page_count is None
    assert dwg.hints.get("doc_class") == "drawing"


class _Doc:
    def __init__(self, classified_by, doc_class, confidence=0.9, flags=(), ext="pdf"):
        self.classified_by, self.doc_class, self.confidence = classified_by, doc_class, confidence
        self.flags, self.ext, self.safety_status = list(flags), ext, "accepted"


def test_rules_routing_only_for_boq_and_addenda_when_ai_is_off():
    f = intake_service._blocked_reason
    assert f(_Doc("rules", "addendum"), 0.85, rules_routing=True) is None
    assert f(_Doc("rules", "boq", ext="xlsx"), 0.85, rules_routing=True) is None
    assert f(_Doc("rules", "drawing"), 0.85, rules_routing=True) is not None
    assert f(_Doc("rules", "addendum"), 0.85, rules_routing=False) is not None  # AI-on tenants: unchanged
    assert f(_Doc("rules", "addendum", confidence=0.5), 0.85, rules_routing=True) is not None
    assert f(_Doc("ai", "drawing"), 0.85, rules_routing=True) is None  # AI proposals behave as before
