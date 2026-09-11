"""Rank fusion and replaceable local reranking."""

from __future__ import annotations

import re
from typing import Protocol, cast

from mini_gl.retrieval.lexical import LexicalSearchService, tokenize
from mini_gl.retrieval.vector import VectorSearchService


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, results: list[dict[str, object]]) -> list[dict[str, object]]: ...


class TokenOverlapReranker:
    name = "entity-aware-local-v2"

    def rerank(self, query: str, results: list[dict[str, object]]) -> list[dict[str, object]]:
        query_terms = set(tokenize(query))
        identifiers = {
            value.casefold()
            for value in re.findall(r"\b(?:[A-Za-z]{2,}\s*)?\d{2,}[A-Za-z-]*\b", query)
        }
        ascii_terms = {
            value.casefold()
            for value in re.findall(r"\b[A-Za-z][A-Za-z0-9+#.-]{2,}\b", query)
        }
        for result in results:
            title = str(result["title"])
            section = str(result.get("section_path", ""))
            text = f"{title} {section} {result['snippet']}"
            overlap = len(query_terms & set(tokenize(text))) / max(1, len(query_terms))
            normalized_title = title.casefold().replace("_", "").replace("-", "")
            identifier_hits = sum(
                identifier.replace(" ", "").replace("-", "") in normalized_title
                for identifier in identifiers
            )
            exact_term_hits = sum(term in text.casefold() for term in ascii_terms)
            result["rerank_score"] = round(overlap, 6)
            result["entity_exact_hits"] = identifier_hits
            result["exact_term_hits"] = exact_term_hits
            result["final_score"] = round(
                _number(result["fusion_score"])
                + overlap * 0.004
                + identifier_hits * 0.02
                + exact_term_hits * 0.015,
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
