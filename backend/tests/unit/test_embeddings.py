"""OnnxEmbedder.embed() -- found live while verifying fix/drawing-pipeline-
resilience (docs/deploy-deltas.md): the ONNX export of BAAI/bge-small-en-
v1.5 is a standard 3-input BERT-family graph (input_ids, attention_mask,
token_type_ids -- confirmed via InferenceSession.get_inputs()), but embed()
only ever supplied the first two. Every real embed_drawing attempt failed
with "Required inputs (['token_type_ids']) are missing" once a real model
was actually provisioned -- previously masked because with no model
provisioned at all, _ensure_loaded() raised FileNotFoundError before this
code ever ran. No CI/dev environment ships the real ~130MB model file, so
this test mocks the ONNX session/tokenizer rather than needing one -- it
only asserts about arguments this call shape, not real embedding output."""

from __future__ import annotations

import numpy as np
import pytest

from app.integrations.embeddings import OnnxEmbedder

_REQUIRED = {
    "APP_DATABASE_URL": "postgresql://x/y",
    "MIGRATOR_DATABASE_URL": "postgresql://x/y",
    "S3_ENDPOINT": "http://s3.test",
    "VLLM_API_BASE": "http://vllm.internal:8000/v1",
}


class _FakeEncoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class _FakeTokenizer:
    def encode(self, text: str) -> _FakeEncoding:
        # One fake token id per character -- deterministic, no real
        # tokenizer vocab needed for this test.
        return _FakeEncoding([ord(c) % 100 for c in text] or [0])


class _FakeSession:
    def __init__(self, hidden: int = 8) -> None:
        self.hidden = hidden
        self.last_feed: dict[str, np.ndarray] | None = None

    def run(self, _output_names, feed: dict[str, np.ndarray]):
        self.last_feed = feed
        batch, seq_len = feed["input_ids"].shape
        # Shape-correct fake token embeddings; values don't matter, only
        # that pooling/normalization downstream doesn't crash on them.
        return [np.ones((batch, seq_len, self.hidden), dtype=np.float32)]


@pytest.fixture
def embedder() -> OnnxEmbedder:
    from app.core.config import Settings

    settings = Settings(**_REQUIRED, EMBEDDING_DIM=8)
    e = OnnxEmbedder(settings)
    e._session = _FakeSession(hidden=8)  # bypass _ensure_loaded's real file/onnxruntime work
    e._tokenizer = _FakeTokenizer()
    return e


def test_embed_passes_token_type_ids_alongside_input_ids_and_attention_mask(embedder: OnnxEmbedder):
    embedder.embed(["hello", "hi"])

    feed = embedder._session.last_feed
    assert feed is not None
    assert set(feed.keys()) == {"input_ids", "attention_mask", "token_type_ids"}


def test_token_type_ids_same_shape_and_dtype_as_input_ids(embedder: OnnxEmbedder):
    embedder.embed(["hello world", "hi"])

    feed = embedder._session.last_feed
    assert feed["token_type_ids"].shape == feed["input_ids"].shape
    assert feed["token_type_ids"].dtype == feed["input_ids"].dtype == np.int64


def test_token_type_ids_are_all_zero_single_sequence_per_row(embedder: OnnxEmbedder):
    """Never a sentence-pair encoding -- every row here is one independent
    text, so the BERT segment id is always 0."""
    embedder.embed(["hello world", "hi", "a longer piece of sheet text"])

    feed = embedder._session.last_feed
    assert (feed["token_type_ids"] == 0).all()


def test_embed_returns_one_vector_per_text_normalized_to_configured_dim(embedder: OnnxEmbedder):
    vectors = embedder.embed(["hello", "world", "a third one"])

    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 8  # EMBEDDING_DIM set on the fixture's Settings
