from __future__ import annotations

from app.takeoff.chunking import build_sheet_chunks


def test_title_block_chunk_created_when_fields_present():
    chunks = build_sheet_chunks(
        sheet_id="s1",
        title_block={"drawing_number": "C-101", "sheet_title": None, "revision": "B"},
        raw_text=None,
    )
    title_chunks = [c for c in chunks if c.chunk_type == "title_block"]
    assert len(title_chunks) == 1
    assert "C-101" in title_chunks[0].content
    assert "B" in title_chunks[0].content
    # None-valued fields are dropped, not rendered as "sheet_title: None"
    assert "sheet_title" not in title_chunks[0].content


def test_no_title_block_chunk_when_all_fields_empty():
    chunks = build_sheet_chunks(sheet_id="s1", title_block={"drawing_number": None}, raw_text=None)
    assert not any(c.chunk_type == "title_block" for c in chunks)


def test_sheet_text_windowing_produces_overlapping_chunks():
    long_text = "A" * 3000  # well beyond one window (400 tokens * 4 chars = 1600 chars)
    chunks = build_sheet_chunks(sheet_id="s1", title_block=None, raw_text=long_text)
    text_chunks = [c for c in chunks if c.chunk_type == "sheet_text"]
    assert len(text_chunks) >= 2
    # windows overlap: the tail of chunk N should reappear at the head of chunk N+1
    overlap_len = 50 * 4
    assert text_chunks[0].content[-overlap_len:] == text_chunks[1].content[:overlap_len]


def test_short_text_produces_single_chunk():
    chunks = build_sheet_chunks(sheet_id="s1", title_block=None, raw_text="short sheet text")
    text_chunks = [c for c in chunks if c.chunk_type == "sheet_text"]
    assert len(text_chunks) == 1
    assert text_chunks[0].content == "short sheet text"


def test_entity_group_chunks_one_per_layer():
    chunks = build_sheet_chunks(
        sheet_id="s1",
        title_block=None,
        raw_text=None,
        entities_by_layer={"PIPE-LABEL": ["DN300", "DN450"], "TEXT-NOTES": ["SEE DETAIL A"]},
    )
    entity_chunks = {c.source_ref["layer"]: c.content for c in chunks if c.chunk_type == "entity_group"}
    assert entity_chunks["PIPE-LABEL"] == "DN300\nDN450"
    assert entity_chunks["TEXT-NOTES"] == "SEE DETAIL A"


def test_empty_layer_text_produces_no_chunk():
    chunks = build_sheet_chunks(sheet_id="s1", title_block=None, raw_text=None, entities_by_layer={"EMPTY": [""]})
    assert not any(c.chunk_type == "entity_group" for c in chunks)


def test_all_empty_inputs_produce_no_chunks():
    assert build_sheet_chunks(sheet_id="s1", title_block=None, raw_text=None) == []
