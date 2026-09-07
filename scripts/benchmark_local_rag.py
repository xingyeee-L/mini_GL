"""Evaluate local Qwen grounded answers using synthetic project documents only."""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from mini_gl.generation import LocalOpenAIChatModel, RAGService
from mini_gl.generation.context import ContextBuilder
from mini_gl.indexing.embeddings import load_bge_provider
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_FIXTURE = ROOT / "tests/fixtures/synthetic/retrieval_benchmark.json"
RAG_FIXTURE = ROOT / "tests/fixtures/synthetic/rag_benchmark.json"
MODEL = "qwen3:4b-instruct-2507-q4_K_M"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    documents = json.loads(RETRIEVAL_FIXTURE.read_text(encoding="utf-8"))["documents"]
    cases = json.loads(RAG_FIXTURE.read_text(encoding="utf-8"))["cases"]
    model = LocalOpenAIChatModel(
        "http://127.0.0.1:11434/v1/chat/completions", MODEL, timeout_seconds=180
    )
    results: list[dict[str, object]] = []
    latencies: list[float] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        allowed = base / "allowed"
        restricted = base / "restricted"
        allowed.mkdir()
        restricted.mkdir()
        for document in documents:
            target = allowed if document["scope"] == "allowed" else restricted
            (target / document["title"]).write_text(document["content"], encoding="utf-8")
        with SQLiteStore(base / "rag.sqlite3") as store:
            ingestion = IngestionService(store)
            source = ingestion.register(allowed)
            ingestion.sync(source.source_id)
            lexical = LexicalSearchService(store)
            lexical.rebuild(source.source_id)
            vector = VectorSearchService(store, load_bge_provider())
            vector.rebuild(source.source_id)
            service = RAGService(
                HybridSearchService(lexical, vector, TokenOverlapReranker()),
                ContextBuilder(store, max_tokens=3_000, max_chunks=6),
                model,
            )
            for case in cases:
                started = time.perf_counter()
                answer = service.answer(case["query"], source.source_id)
                latencies.append((time.perf_counter() - started) * 1_000)
                titles = {citation.title for citation in answer.citations}
                citation_ok = set(case["citations"]).issubset(titles)
                keyword_ok = not case["keywords"] or any(
                    keyword.casefold() in answer.answer.casefold() for keyword in case["keywords"]
                )
                abstention_ok = answer.insufficient_evidence == case.get("insufficient", False)
                results.append(
                    {
                        "id": case["id"],
                        "passed": citation_ok and keyword_ok and abstention_ok,
                        "citation_ok": citation_ok,
                        "keyword_ok": keyword_ok,
                        "abstention_ok": abstention_ok,
                        "retrieval_ms": answer.retrieval_ms,
                        "generation_ms": answer.generation_ms,
                        "prompt_tokens": answer.prompt_tokens,
                        "completion_tokens": answer.completion_tokens,
                    }
                )
    report = {
        "model": MODEL,
        "cases": len(results),
        "passed": sum(bool(result["passed"]) for result in results),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 2),
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
