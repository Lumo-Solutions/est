"""Module B/C Phase 5: pure-logic unit coverage. Integration-level
suggestion/RAG-ranking behavior (real pgvector columns, a fixture embedder)
lives in tests/integration/test_semantic_matching.py -- these tests never
touch a DB or a real embedder."""

from __future__ import annotations

import pytest

from app.integrations import embeddings as embeddings_module
from app.services.semantic_matching import (
    build_measurement_descriptor,
    combine_scores,
    cosine_similarity_from_distance,
)


class _FakeEmbedder:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._raises is not None:
            raise self._raises
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_embed_best_effort_returns_none_when_model_not_provisioned(monkeypatch):
    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: _FakeEmbedder(raises=FileNotFoundError("no model")))
    assert embeddings_module.embed_best_effort(["hello"]) is None


def test_embed_best_effort_propagates_unexpected_errors(monkeypatch):
    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: _FakeEmbedder(raises=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        embeddings_module.embed_best_effort(["hello"])


def test_embed_best_effort_returns_vectors_on_success(monkeypatch):
    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: _FakeEmbedder())
    result = embeddings_module.embed_best_effort(["a", "b"])
    assert result == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]


def test_combine_scores_falls_back_to_fuzzy_only_when_no_semantic_score():
    assert combine_scores(0.8, None) == 0.8


def test_combine_scores_weights_fuzzy_over_semantic():
    # 0.6*1.0 + 0.4*0.0 = 0.6
    assert combine_scores(1.0, 0.0) == pytest.approx(0.6)
    # 0.6*0.0 + 0.4*1.0 = 0.4
    assert combine_scores(0.0, 1.0) == pytest.approx(0.4)


def test_cosine_similarity_from_distance_clamps_to_zero_one():
    assert cosine_similarity_from_distance(0.0) == 1.0  # identical vectors
    assert cosine_similarity_from_distance(1.0) == 0.0  # orthogonal
    assert cosine_similarity_from_distance(2.0) == 0.0  # opposite -- clamped, never a penalty
    assert cosine_similarity_from_distance(-0.3) == 1.0  # never above 1 either


def test_build_measurement_descriptor_formats_known_and_unknown_fields():
    full = build_measurement_descriptor(capability="alignment", kind="alignment_length_m", layer="ROAD-CL", trade_name="Roadworks")
    assert full == "alignment alignment_length_m layer=ROAD-CL trade=Roadworks"

    sparse = build_measurement_descriptor(capability="alignment", kind="alignment_length_m", layer=None, trade_name=None)
    assert sparse == "alignment alignment_length_m layer=unknown trade=unclassified"
