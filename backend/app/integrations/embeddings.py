from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

from app.core.config import Settings, get_settings


class EmbeddingBackend(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OnnxEmbedder:
    """CPU-only embeddings via ONNX Runtime (A8: keeps the GPU free for the
    vision-language model). Model files are provisioned offline via
    ai-service/embeddings/download_model.py into ONNX_MODEL_DIR."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self._dim = settings.embedding_dim
        self._model_dir = Path(settings.onnx_model_dir) / settings.embedding_model.replace("/", "_")
        self._session = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = self._model_dir / "model.onnx"
        tokenizer_path = self._model_dir / "tokenizer.json"
        if not model_path.exists() or not tokenizer_path.exists():
            raise FileNotFoundError(
                f"ONNX embedding model not found at {self._model_dir}. Run "
                "ai-service/embeddings/download_model.py to provision it."
            )
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        assert self._session is not None and self._tokenizer is not None

        encodings = [self._tokenizer.encode(t) for t in texts]
        max_len = max((len(e.ids) for e in encodings), default=1)
        input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
        attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
        for i, enc in enumerate(encodings):
            n = len(enc.ids)
            input_ids[i, :n] = enc.ids
            attention_mask[i, :n] = 1

        outputs = self._session.run(
            None, {"input_ids": input_ids, "attention_mask": attention_mask}
        )
        token_embeddings = outputs[0]  # (batch, seq_len, hidden)
        mask = attention_mask[..., None].astype(np.float32)
        summed = (token_embeddings * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.clip(norms, 1e-9, None)
        return normalized[:, : self._dim].tolist()


class VllmEmbedder:
    """Alternative backend: embeddings served by vLLM itself, for
    deployments that would rather not run a second (CPU) inference path.
    Not the default (A8) -- switch via EMBEDDING_BACKEND=vllm."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self._settings = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        # NOTE: only safe to call from a plain sync context (no event loop
        # already running in this thread) -- EMBEDDING_BACKEND=onnx is the
        # default (A8) specifically to avoid this backend's async bridging.
        import asyncio

        from openai import AsyncOpenAI

        async def _run() -> list[list[float]]:
            client = AsyncOpenAI(base_url=self._settings.vllm_api_base, api_key=self._settings.vllm_api_key)
            resp = await client.embeddings.create(model=self._settings.embedding_model, input=texts)
            return [d.embedding for d in resp.data]

        return asyncio.run(_run())


@lru_cache
def get_embedder() -> EmbeddingBackend:
    settings = get_settings()
    if settings.embedding_backend == "vllm":
        return VllmEmbedder(settings)
    return OnnxEmbedder(settings)
