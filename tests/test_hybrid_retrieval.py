from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_gl.indexing.embeddings import DeterministicLocalEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore


class CountingEmbedding(DeterministicLocalEmbedding):
    name = "counting-test-v1"

    def __init__(self) -> None:
        super().__init__(64)
        self.embedded = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded += len(texts)
        return super().embed(texts)


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        root = base / "source"
        root.mkdir()
        (root / "security.md").write_text(
            "系统只读访问授权目录，并拒绝符号链接。", encoding="utf-8"
        )
        (root / "recovery.md").write_text(
            "程序崩溃后清理暂存数据，从最近成功游标恢复。", encoding="utf-8"
        )
        self.store = SQLiteStore(base / "state.sqlite3")
        ingestion = IngestionService(self.store)
        self.source = ingestion.register(root)
        ingestion.sync(self.source.source_id)
        self.lexical = LexicalSearchService(self.store)
        self.lexical.rebuild(self.source.source_id)
        self.provider = DeterministicLocalEmbedding(64)
        self.vector = VectorSearchService(self.store, self.provider)
        self.vector.rebuild(self.source.source_id, batch_size=1)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_vector_index_is_stable_and_scoped(self) -> None:
        first = self.vector.search("拒绝符号链接", self.source.source_id)
        self.vector.rebuild(self.source.source_id)
        second = self.vector.search("拒绝符号链接", self.source.source_id)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["title"], "security.md")
        self.assertEqual(self.vector.search("符号链接", "unknown-source"), [])

    def test_hybrid_fusion_and_reranking(self) -> None:
        hybrid = HybridSearchService(
            self.lexical, self.vector, TokenOverlapReranker()
        )
        results = hybrid.search("崩溃后如何恢复", self.source.source_id)
        self.assertEqual(results[0]["title"], "recovery.md")
        self.assertIn("fusion_score", results[0])
        self.assertIn("rerank_score", results[0])

    def test_provider_rejects_invalid_dimension(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 32"):
            DeterministicLocalEmbedding(8)

    def test_incremental_index_reuses_updates_and_deletes_vectors(self) -> None:
        provider = CountingEmbedding()
        vector = VectorSearchService(self.store, provider)
        first = vector.sync(self.source.source_id)
        self.assertEqual(first["embedded"], 2)

        second = vector.sync(self.source.source_id)
        self.assertEqual(second["embedded"], 0)
        self.assertEqual(second["reused"], 2)

        root = self.source.root_path
        (root / "security.md").write_text("系统拒绝符号链接和目录联接。", encoding="utf-8")
        (root / "recovery.md").unlink()
        IngestionService(self.store).sync(self.source.source_id)
        lexical = self.lexical.sync(self.source.source_id)
        updated = vector.sync(self.source.source_id)

        self.assertEqual(lexical["created"], 1)
        self.assertEqual(lexical["deleted"], 1)
        self.assertEqual(updated["embedded"], 1)
        self.assertEqual(updated["chunks"], 1)
        self.assertEqual(provider.embedded, 3)

    def test_multiple_provider_indexes_can_coexist(self) -> None:
        other = CountingEmbedding()
        VectorSearchService(self.store, other).sync(self.source.source_id)
        providers = self.store.connection.execute(
            "SELECT COUNT(DISTINCT provider) FROM vector_chunks"
        ).fetchone()[0]
        self.assertEqual(providers, 2)
