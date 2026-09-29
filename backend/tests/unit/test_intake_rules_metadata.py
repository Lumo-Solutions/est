"""Tender intake stage 1: every rule, the metadata regexes, addendum reference
parsing and revision ordering (app/intake/rules.py, metadata.py)."""

from __future__ import annotations

import pytest

from app.intake.extract import DocContent, SheetInfo, detect_header
from app.intake.metadata import (
    discipline_to_sub_type,
    extract_metadata,
    parse_supersede_refs,
    revision_sort_key,
)
from app.intake.rules import CONFLICT_RUNNER_UP, classify_rules, combine, needs_model, Hit


def _content(text: str = "", *, filename: str = "x.pdf", ext: str = "pdf", **kw) -> DocContent:
    c = DocContent(filename=filename, ext=ext, sniffed=ext, text=text, page_texts=[text] if text else [], **kw)
    c.has_text_layer = bool(text.strip())
    return c


# ------------------------------------------------------------------ rules
@pytest.mark.parametrize(
    "text, expected, rule",
    [
        ("ADDENDUM No. 3\nIssue date: 1 May 2026", "addendum", "addendum_title"),
        ("BILL OF QUANTITIES\nPreliminaries", "boq", "boq_title"),
        ("CONDITIONS OF CONTRACT\nFIDIC Red Book", "contract", "contract_terms"),
        ("Particular Conditions of Contract", "contract", "contract_terms"),
        ("INSTRUCTIONS TO TENDERERS\n1. General", "tender_instructions", "instructions_to_tenderers"),
        ("FORM OF TENDER\nWe offer to execute", "tender_forms", "tender_forms"),
        ("BID BOND\nKnow all men", "tender_forms", "tender_forms"),
        ("REQUEST FOR INFORMATION\nRFI No. 07", "clarification", "clarification"),
        ("CONSTRUCTION PROGRAMME\nBaseline", "programme", "programme"),
        ("GEOTECHNICAL INVESTIGATION REPORT\nBorehole BH-01", "site_investigation", "geotechnical"),
        ("SECTION 03 30 00 CAST-IN-PLACE CONCRETE\nPART 1 GENERAL", "specification", "spec_section"),
        ("Dear Sirs,\nFurther to our meeting", "correspondence", "letter_phrases"),
    ],
)
def test_each_text_rule(text, expected, rule):
    out = classify_rules(_content(text, filename="scan.pdf"))
    assert out.doc_class == expected
    assert rule in {e["rule"] for e in out.evidence}
    assert out.confidence >= 0.7


def test_dxf_extension_means_drawing_even_without_text():
    c = DocContent(filename="x.dxf", ext="dxf", sniffed="dxf")
    out = classify_rules(c)
    assert (out.doc_class, out.confidence) == ("drawing", 0.95)
    assert not needs_model(out, 0.85)


def test_dwg_is_a_drawing():
    out = classify_rules(DocContent(filename="site.dwg", ext="dwg", sniffed="dwg"))
    assert out.doc_class == "drawing" and out.confidence >= 0.9
    assert {"ext_dwg"} <= {e["rule"] for e in out.evidence}


def test_xlsx_header_sniff_makes_a_boq_and_reports_sheet_and_row():
    cols = ["Item No", "Description", "Unit", "Qty", "Rate", "Amount"]
    rows = [[None], ["Bill"], cols, ["1.0", "Earthworks", None, None, None, None]]
    row, score, found = detect_header(rows)
    assert (row, score) == (3, 6) and found == cols
    c = _content("[BOQ]", filename="pricing.xlsx", ext="xlsx", sheets=[SheetInfo("Summary"), SheetInfo("BOQ", 3, 6, cols, "")])
    out = classify_rules(c)
    assert out.doc_class == "boq" and out.confidence >= 0.95
    assert out.metadata["boq_sheet"] == "BOQ" and out.metadata["header_row"] == 3
    assert out.metadata["sheet_names"] == ["Summary", "BOQ"]


def test_header_row_needs_three_groups():
    assert detect_header([["Item", "Description"]])[0] is None
    assert detect_header([["Item", "Description", "Qty"]])[0] == 1


def test_title_block_regex_marks_a_pdf_drawing():
    c = _content("Site plan", filename="sheet.pdf", title_block_text="DRAWING NO. S-201\nREV B\nSCALE 1:100")
    out = classify_rules(c)
    assert out.doc_class == "drawing"
    assert "title_block" in {e["rule"] for e in out.evidence}
    assert out.metadata["document_number"] == "S-201" and out.metadata["revision"] == "B" and out.metadata["scale"] == "1:100"
    assert out.sub_type == "structural"


def test_vector_density_backs_up_a_drawing_but_alone_is_moderate():
    c = _content("", filename="unknown.pdf", vector_density=900)
    out = classify_rules(c)
    assert out.doc_class == "drawing" and out.confidence == pytest.approx(0.65)
    assert needs_model(out, 0.85)


def test_raster_pdf_with_no_text_is_low_confidence_other():
    c = DocContent(filename="Scan_0042.pdf", ext="pdf", sniffed="pdf", is_raster=True, needs_image=True)
    out = classify_rules(c)
    assert out.doc_class == "other" and out.confidence < 0.3 and needs_model(out, 0.85)


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("ADD-01.pdf", "addendum"),
        ("BOQ_Rev0.xlsx", "boq"),
        ("C-101 Rev B.pdf", "drawing"),
        ("SPEC_Concrete.pdf", "specification"),
        ("Conditions_of_Contract.pdf", "contract"),
        ("ITT.pdf", "tender_instructions"),
        ("RFI_07.pdf", "clarification"),
        ("Programme.pdf", "programme"),
        ("Geotech_BH.pdf", "site_investigation"),
        ("Letter_from_Client.pdf", "correspondence"),
    ],
)
def test_filename_patterns(filename, expected):
    out = classify_rules(DocContent(filename=filename, ext=filename.rsplit(".", 1)[1], sniffed=None))
    assert out.doc_class == expected
    assert 0.5 <= out.confidence < 0.85  # filename alone is never enough to skip the model


def test_no_signal_falls_back_to_other_low():
    out = classify_rules(_content("some text about nothing much", filename="Notes.csv", ext="csv"))
    assert out.doc_class == "other" and out.confidence == 0.2


def test_keyword_in_the_body_counts_half_so_an_addendum_is_not_a_boq():
    text = "ADDENDUM No. 1\nIssue date: 12 March 2026\nThis addendum supersedes drawing C-101 Rev A.\nBill of Quantities item 1.1 is amended."
    out = classify_rules(_content(text, filename="ADD-01.pdf"))
    assert out.doc_class == "addendum"
    assert out.candidates["boq"] < CONFLICT_RUNNER_UP
    assert not out.conflict and not needs_model(out, 0.85)


def test_a_real_conflict_is_flagged():
    out = classify_rules(_content("BILL OF QUANTITIES\nADDENDUM No. 2", filename="x.pdf"))
    assert out.conflict and needs_model(out, 0.85)


def test_combine_is_noisy_or_and_capped():
    scores = combine([Hit("boq", 0.9, "a", ""), Hit("boq", 0.9, "b", ""), Hit("boq", 0.9, "c", "")])
    assert scores["boq"] == 0.98
    assert combine([Hit("boq", 0.5, "a", ""), Hit("boq", 0.5, "b", "")])["boq"] == pytest.approx(0.75)


# ------------------------------------------------------------------ metadata
def test_labelled_number_revision_title_scale_sheet_discipline_date():
    c = _content(
        "DRAWING NO: C-101\nREV: A\nTITLE: Site Grading Plan\nSCALE 1:200\nSheet 2 of 5\nDISCIPLINE: Civil\nDate: 12 March 2026",
        filename="C-101.dxf",
        ext="dxf",
    )
    md = extract_metadata(c)
    assert md["document_number"] == "C-101"
    assert md["revision"] == "A"
    assert md["title"] == "Site Grading Plan"
    assert md["scale"] == "1:200"
    assert md["sheet_number"] == "2 of 5"
    assert md["discipline"] == "Civil"
    assert md["date"] == "12 March 2026"


def test_revision_falls_back_to_the_filename_and_does_not_read_review():
    c = _content("Please review the attached", filename="C-101 Rev B.dxf", ext="dxf")
    assert extract_metadata(c)["revision"] == "B"


def test_dates_in_three_formats():
    for text, expected in (("Issue date: 2026-03-12", "2026-03-12"), ("Issue date: 12/03/2026", "12/03/2026"), ("Issued: 12 Mar 2026", "12 Mar 2026")):
        md = extract_metadata(_content(f"ADDENDUM No. 1\n{text}"))
        assert md["addendum_issue_date"] == expected


def test_addendum_number_issue_date_and_supersedes():
    text = "ADDENDUM No. 4\nIssue date: 12 March 2026\nThis addendum supersedes drawing C-101 Rev A. Drawing C-101 Rev B is issued in its place.\nBill of Quantities item 1.1 Excavation is amended from 500 m3 to 650 m3."
    md = extract_metadata(_content(text, filename="ADD-04.pdf"))
    assert md["addendum_number"] == "4"
    assert md["addendum_issue_date"] == "12 March 2026"
    assert md["supersedes"] == ["C-101 Rev A"]
    assert md["amends"] == ["BOQ"]


def test_supersede_refs_actions_and_dedup():
    refs = parse_supersede_refs("Drawing S-201 Rev A is withdrawn. Drawings A-100 and A-101 Rev C are amended. S-201 Rev A is withdrawn again.")
    assert [(r.reference_text, r.action) for r in refs] == [("S-201 Rev A", "supersedes"), ("A-100", "amends"), ("A-101 Rev C", "amends")]
    assert parse_supersede_refs("Nothing to see here C-101.") == []


def test_discipline_sub_types():
    assert discipline_to_sub_type("Civil", None) == "civil_infra"
    assert discipline_to_sub_type("MEP services", None) == "mep"
    assert discipline_to_sub_type(None, "A-201") == "architectural"
    assert discipline_to_sub_type(None, "L-001") == "landscape"
    assert discipline_to_sub_type(None, None, ["S-BEAM"]) == "structural"
    assert discipline_to_sub_type(None, None) is None


def test_revision_ordering_numeric_alpha_and_none():
    revs = ["B", "A", None, "2", "1", "C"]
    assert sorted(revs, key=revision_sort_key) == [None, "1", "2", "A", "B", "C"]
    assert revision_sort_key("AA") > revision_sort_key("Z")
