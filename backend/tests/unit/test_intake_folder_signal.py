"""Folder path as a classification signal (folder upload): weak-to-moderate,
never enough to override what a document says about itself."""

from __future__ import annotations

from app.intake.extract import DocContent
from app.intake.rules import classify_rules, normalise_folder


def _c(name="scan_001.pdf", text=""):
    return DocContent(filename=name, ext="pdf", sniffed="pdf", text=text, page_texts=[text] if text else [], has_text_layer=bool(text))


def test_normalise_folder_strips_filename_and_traversal():
    assert normalise_folder("Tender/Drawings/C-101.pdf") == "Tender/Drawings"
    assert normalise_folder(r"a\b\c.pdf") == "a/b"
    assert normalise_folder("../../etc/x.pdf") == "etc"
    assert normalise_folder("C-101.pdf") == "" and normalise_folder(None) == ""


def test_folder_name_moves_an_otherwise_unknown_file():
    plain = classify_rules(_c())
    assert plain.doc_class == "other"
    with_folder = classify_rules(_c(), folder="Tender Package/Drawings")
    assert with_folder.doc_class == "drawing"
    assert any(e["rule"] == "folder_drawings" for e in with_folder.evidence)
    assert classify_rules(_c(), folder="Tender/Addenda").doc_class == "addendum"
    assert classify_rules(_c(), folder="Tender/Geotechnical Reports").doc_class == "site_investigation"


def test_nearest_folder_beats_ancestor():
    out = classify_rules(_c(), folder="Contract/BOQ")
    assert out.doc_class == "boq"


def test_content_overrides_a_misleading_folder():
    text = "ADDENDUM No. 2\nThis addendum amends the drawings."
    out = classify_rules(_c("misc.pdf", text), folder="Tender/Drawings")
    assert out.doc_class == "addendum"


def test_folder_word_must_be_a_whole_word():
    assert classify_rules(_c(), folder="Tender/Planning permits").doc_class == "other"  # 'plan' is not 'planning'
    assert classify_rules(_c(), folder="Tender/Waterproofing").doc_class == "other"
