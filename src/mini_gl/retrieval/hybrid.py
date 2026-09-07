"""Rank fusion and replaceable local reranking."""

from __future__ import annotations

from typing import Protocol, cast

from mini_gl.retrieval.lexical import LexicalSearchService, tokenize
from mini_gl.retrieval.vector import VectorSearchService


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, results: list[dict[str, object]]) -> list[dict[str, object]]: ...


class TokenOverlapReranker:
    name = "token-overlap-v1"

    def rerank(self, query: str, results: list[dict[str, object]]) -> list[dict[str, object]]:
        query_terms = set(tokenize(query))
        for result in results:
            text = f"{result['title']} {result['snippet']}"
            overlap = len(query_terms & set(tokenize(text))) / max(1, len(query_terms))
            result["rerank_score"] = round(overlap, 6)
            result["final_score"] = round(
                _number(result["fusion_score"]) + overlap * 0.001,
                8,
            )
        return sorted(
            results,
            key=lambda result: (
                -_number(result["final_score"]),
                str(result["chunk_id"]),
            ),
        )


class HybridSearchService:
    def __init__(
        self,
        lexical: LexicalSearchService,
        vector: VectorSearchService,
        reranker: Reranker | None = None,
    ) -> None:
        self.lexical = lexical
        self.vector = vector
        self.reranker = reranker

    def search(
        self,
        query: str,
        source_id: str,
        limit: int = 10,
        *,
        file_type: str | None = None,
        updated_after: str | None = None,
    ) -> list[dict[str, object]]:
        lexical_response = self.lexical.search(
            query,
            source_id=source_id,
            file_type=file_type,
            updated_after=updated_after,
            limit=50,
        )
        lexical_rows = cast(list[dict[str, object]], lexical_response["results"])
        vector_rows = self.vector.search(
            query,
            source_id,
            limit=50,
            file_type=file_type,
            updated_after=updated_after,
        )
        fused: dict[str, dict[str, object]] = {}
        channels = (("lexical", lexical_rows, 1.0), ("vector", vector_rows, 2.0))
        for channel, rows, weight in channels:
            for rank, result in enumerate(rows, 1):
                chunk_id = str(result["chunk_id"])
                item = fused.setdefault(chunk_id, dict(result))
                item["fusion_score"] = (
                    _number(item.get("fusion_score", 0.0)) + weight / (60 + rank)
                )
                item[f"{channel}_rank"] = rank
                item[f"{channel}_score"] = result["score"]
        results = list(fused.values())
        results.sort(
            key=lambda result: (-_number(result["fusion_score"]), str(result["chunk_id"]))
        )
        if self.reranker:
            results = self.reranker.rerank(query, results)
        return results[: max(1, min(limit, 50))]


def _number(value: object) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError("Expected a numeric ranking score")
    return float(value)
