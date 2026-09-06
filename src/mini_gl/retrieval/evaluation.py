"""Offline retrieval quality metrics for synthetic query sets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median
from typing import cast

from mini_gl.retrieval.lexical import LexicalSearchService


@dataclass(frozen=True, slots=True)
class EvaluationQuery:
    query: str
    relevant_titles: frozenset[str]
    forbidden_titles: frozenset[str] = frozenset()


def evaluate(
    service: LexicalSearchService,
    queries: Iterable[EvaluationQuery],
    *,
    source_id: str | None = None,
) -> dict[str, float]:
    cases = list(queries)
    if not cases:
        return {
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0,
            "forbidden_result_rate": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }
    recall_5 = recall_10 = reciprocal_rank = 0.0
    forbidden = returned = 0
    latencies: list[float] = []
    for case in cases:
        response = service.search(case.query, source_id=source_id, limit=10)
        results = cast(list[dict[str, object]], response["results"])
        titles = [str(result["title"]) for result in results]
        latencies.append(cast(float, response["elapsed_ms"]))
        forbidden += sum(title in case.forbidden_titles for title in titles)
        returned += len(titles)
        recall_5 += _recall(titles[:5], case.relevant_titles)
        recall_10 += _recall(titles[:10], case.relevant_titles)
        reciprocal_rank += next(
            (1 / rank for rank, title in enumerate(titles, 1) if title in case.relevant_titles),
            0.0,
        )
    count = len(cases)
    return {
        "recall_at_5": round(recall_5 / count, 4),
        "recall_at_10": round(recall_10 / count, 4),
        "mrr": round(reciprocal_rank / count, 4),
        "forbidden_result_rate": round(forbidden / returned, 4) if returned else 0.0,
        "p50_ms": round(median(latencies), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
    }


def _recall(titles: list[str], relevant: frozenset[str]) -> float:
    return len(set(titles) & relevant) / len(relevant) if relevant else 1.0


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction
