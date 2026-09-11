from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.indexing.embeddings import DeterministicLocalEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore


class Phase10TrustBenchmarkTests(unittest.TestCase):
    def test_course_entity_retrieval_has_perfect_top_one_on_synthetic_set(self) -> None:
        fixture_root = Path(__file__).parent / "fixtures" / "synthetic"
        cases = json.loads(
            (fixture_root / "phase10_trust_benchmark.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteStore(Path(temporary) / "state.sqlite3") as store:
                ingestion = IngestionService(store)
                source = ingestion.register(fixture_root / "phase10_courses")
                ingestion.sync(source.source_id)
                lexical = LexicalSearchService(store)
                lexical.rebuild(source.source_id)
                vector = VectorSearchService(store, DeterministicLocalEmbedding(64))
                vector.rebuild(source.source_id)
                hybrid = HybridSearchService(lexical, vector, TokenOverlapReranker())

                hits = 0
                for case in cases:
                    results = hybrid.search(case["query"], source.source_id, limit=5)
                    hits += bool(results and results[0]["title"] == case["relevant"])
                self.assertEqual(hits / len(cases), 1.0)

                sections = store.connection.execute(
                    "SELECT DISTINCT section_path FROM lexical_chunks WHERE source_id=?",
                    (source.source_id,),
                ).fetchall()
                self.assertIn("UCB CS61A › 课程定位", {row[0] for row in sections})


if __name__ == "__main__":
    unittest.main()
