from __future__ import annotations

from dataclasses import dataclass

_WINDOW_TOKENS = 400
_OVERLAP_TOKENS = 50
_CHARS_PER_TOKEN = 4  # rough heuristic, avoids pulling in a tokenizer here


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_type: str  # title_block | sheet_text | entity_group
    content: str
    source_ref: dict


def _windowed_text(text: str, window_chars: int, overlap_chars: int) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + window_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap_chars
    return chunks


def build_sheet_chunks(
    *,
    sheet_id: str,
    title_block: dict | None,
    raw_text: str | None,
    entities_by_layer: dict[str, list[str]] | None = None,
) -> list[Chunk]:
    """Splits one sheet into RAG chunks: one title-block record, windowed
    body-text chunks (400 tokens / ~50 overlap), and one chunk per layer
    grouping entity text (e.g. all PIPE-LABEL layer text together)."""
    chunks: list[Chunk] = []

    if title_block:
        fields = ", ".join(f"{k}: {v}" for k, v in title_block.items() if v)
        if fields:
            chunks.append(Chunk("title_block", fields, {"sheet_id": sheet_id}))

    if raw_text:
        window_chars = _WINDOW_TOKENS * _CHARS_PER_TOKEN
        overlap_chars = _OVERLAP_TOKENS * _CHARS_PER_TOKEN
        for i, window in enumerate(_windowed_text(raw_text, window_chars, overlap_chars)):
            chunks.append(Chunk("sheet_text", window, {"sheet_id": sheet_id, "window_index": i}))

    for layer, texts in (entities_by_layer or {}).items():
        joined = "\n".join(texts)
        if joined.strip():
            chunks.append(Chunk("entity_group", joined, {"sheet_id": sheet_id, "layer": layer}))

    return chunks
