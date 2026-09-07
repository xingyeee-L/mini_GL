"""Replaceable, offline embedding provider boundary."""

from __future__ import annotations

import hashlib
import importlib
import math
import os
from pathlib import Path
from typing import Any, Protocol

from mini_gl.retrieval.lexical import tokenize

BGE_MODEL_ID = "BAAI/bge-small-zh-v1.5"
BGE_MODEL_REVISION = "a7ec18349c42fc774b0e86af26215e38a10fbe9d"
BGE_DEFAULT_PATH = Path("models/bge-small-zh-v1.5")


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DeterministicLocalEmbedding:
    """Dependency-free projection for plumbing tests, not a semantic model."""

    name = "deterministic-local-v1"

    def __init__(self, dimension: int = 256) -> None:
        if dimension < 32:
            raise ValueError("Embedding dimension must be at least 32")
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in tokenize(text):
            digest = hashlib.sha256(term.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class SentenceTransformerEmbedding:
    """Strictly local sentence-transformers provider for downloaded model weights."""

    def __init__(self, model_path: Path, *, model_id: str, revision: str) -> None:
        if not model_path.is_dir():
            raise FileNotFoundError(f"Local embedding model not found: {model_path}")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        module = importlib.import_module("sentence_transformers")
        model_class: Any = module.SentenceTransformer
        self._model: Any = model_class(
            str(model_path),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
        )
        dimension = self._model.get_embedding_dimension()
        if not isinstance(dimension, int):
            raise ValueError("Model did not report an embedding dimension")
        self.dimension = dimension
        self.name = f"sentence-transformers:{model_id}@{revision}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: Any = self._model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in vectors]


def load_bge_provider(model_path: Path = BGE_DEFAULT_PATH) -> SentenceTransformerEmbedding:
    return SentenceTransformerEmbedding(
        model_path.resolve(), model_id=BGE_MODEL_ID, revision=BGE_MODEL_REVISION
    )
