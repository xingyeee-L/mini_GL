from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.evaluation import EvaluationQuery, evaluate
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.storage.sqlite import SQLiteStore

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "retrieval_benchmark.json"


class ChineseRetrievalBenchmarkTests(unittest.TestCase):
    def test_expanded_synthetic_benchmark(self) -> None:
        benchmark = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(benchmark["version"], 1)
        self.assertGreaterEqual(len(benchmark["documents"]), 15)
        self.assertGreaterEqual(len(benchmark["queries"]), 25)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            allowed = base / "allowed"
            restricted = base / "restricted"
            allowed.mkdir()
            restricted.mkdir()
            for document in benchmark["documents"]:
                root = allowed if document["scope"] == "allowed" else restricted
                (root / document["title"]).write_text(document["content"], encoding="utf-8")

            with SQLiteStore(base / "benchmark.sqlite3") as store:
                ingestion = IngestionService(store)
                allowed_source = ingestion.register(allowed)
                restricted_source = ingestion.register(restricted)
                ingestion.sync(allowed_source.source_id)
                ingestion.sync(restricted_source.source_id)
                search = LexicalSearchService(store)
                search.rebuild()
                queries = [
                    EvaluationQuery(
                        case["query"],
                        frozenset(case["relevant"]),
                        frozenset(case.get("forbidden", [])),
                    )
                    for case in benchmark["queries"]
                ]
                metrics = evaluate(search, queries, source_id=allowed_source.source_id)

        # These are regression gates for the improved lexical baseline, not target quality.
        self.assertGreaterEqual(metrics["recall_at_5"], 0.60, metrics)
        self.assertGreaterEqual(metrics["recall_at_10"], 0.60, metrics)
        self.assertGreaterEqual(metrics["mrr"], 0.50, metrics)
        self.assertEqual(metrics["forbidden_result_rate"], 0.0)
        self.assertGreaterEqual(metrics["p95_ms"], metrics["p50_ms"])
