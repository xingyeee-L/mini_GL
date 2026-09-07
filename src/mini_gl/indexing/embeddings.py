"""Replaceable, offline embedding provider boundary."""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from mini_gl.retrieval.lexical import tokenize


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
