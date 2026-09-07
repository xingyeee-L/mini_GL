"""Compare frozen Chinese retrieval quality using a downloaded local model."""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from mini_gl.indexing.embeddings import SentenceTransformerEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic" / "retrieval_benchmark.json"
MODEL_PATH = ROOT / "models" / "bge-small-zh-v1.5"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "a7ec18349c42fc774b0e86af26215e38a10fbe9d"


def metrics(
    cases: list[dict[str, object]], search: Callable[[str], list[dict[str, object]]]
) -> dict[str, float]:
    recalls_5: list[float] = []
    recalls_10: list[float] = []
    ranks: list[float] = []
    latencies: list[float] = []
    forbidden = returned = 0
    for case in cases:
        started = time.perf_counter()
        rows = search(str(case["query"]))
        latencies.append((time.perf_counter() - started) * 1000)
        titles = [str(row["title"]) for row in rows]
        relevant = set(case["relevant"])
        denied = set(case.get("forbidden", []))
        recalls_5.append(len(set(titles[:5]) & relevant) / len(relevant) if relevant else 1.0)
        recalls_10.append(len(set(titles[:10]) & relevant) / len(relevant) if relevant else 1.0)
        ranks.append(
            next((1 / rank for rank, title in enumerate(titles, 1) if title in relevant), 0)
        )
        forbidden += sum(title in denied for title in titles)
        returned += len(titles)
    return {
        "recall_at_5": round(statistics.mean(recalls_5), 4),
        "recall_at_10": round(statistics.mean(recalls_10), 4),
        "mrr": round(statistics.mean(ranks), 4),
        "forbidden_result_rate": round(forbidden / returned, 4) if returned else 0.0,
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 2),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    benchmark = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provider = SentenceTransformerEmbedding(
        MODEL_PATH, model_id=MODEL_ID, revision=MODEL_REVISION
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        allowed = base / "allowed"
        restricted = base / "restricted"
        allowed.mkdir()
        restricted.mkdir()
        for document in benchmark["documents"]:
            target = allowed if document["scope"] == "allowed" else restricted
            (target / document["title"]).write_text(document["content"], encoding="utf-8")
        with SQLiteStore(base / "benchmark.sqlite3") as store:
            ingestion = IngestionService(store)
            allowed_source = ingestion.register(allowed)
            restricted_source = ingestion.register(restricted)
            ingestion.sync(allowed_source.source_id)
            ingestion.sync(restricted_source.source_id)
            lexical = LexicalSearchService(store)
            lexical.rebuild()
            vector = VectorSearchService(store, provider)
            index_started = time.perf_counter()
            vector.rebuild()
            index_ms = (time.perf_counter() - index_started) * 1000
            hybrid = HybridSearchService(lexical, vector, TokenOverlapReranker())
            cases = benchmark["queries"]
            report = {
                "model": provider.name,
                "dimension": provider.dimension,
                "index_ms": round(index_ms, 2),
                "vector": metrics(
                    cases, lambda query: vector.search(query, allowed_source.source_id)
                ),
                "hybrid": metrics(
                    cases, lambda query: hybrid.search(query, allowed_source.source_id)
                ),
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
