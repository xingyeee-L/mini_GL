from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.evaluation import EvaluationQuery, diagnose, evaluate
from mini_gl.retrieval.lexical import LexicalSearchService, tokenize
from mini_gl.storage.sqlite import SQLiteStore


class LexicalRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "security.md").write_text(
            "# 安全设计\n\n系统只读访问授权目录，并拒绝符号链接。", encoding="utf-8"
        )
        (self.root / "search.txt").write_text(
            "关键词检索使用 BM25 排序，并保留原始文件来源。", encoding="utf-8"
        )
        (self.root / "cooking.txt").write_text(
            "今天的晚饭是番茄炒蛋。", encoding="utf-8"
        )
        self.store = SQLiteStore(self.base / "state.sqlite3")
        ingestion = IngestionService(self.store)
        self.source = ingestion.register(self.root)
        ingestion.sync(self.source.source_id)
        self.search = LexicalSearchService(self.store)
        self.search.rebuild(self.source.source_id)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_chinese_tokenization_and_ranking(self) -> None:
        self.assertIn("安全", tokenize("安全设计"))
        self.assertIn("utf16", tokenize("UTF-16 编码"))
        self.assertNotIn("如何", tokenize("如何保护文件"))
        result = self.search.search("如何拒绝符号链接", source_id=self.source.source_id)
        rows = result["results"]
        self.assertIsInstance(rows, list)
        self.assertEqual(rows[0]["title"], "security.md")
        self.assertIn("符号链接", rows[0]["snippet"])
        self.assertNotIn("今天的晚饭", str(rows))

    def test_stable_ids_and_file_type_filter(self) -> None:
        first = self.search.search("来源", source_id=self.source.source_id)
        self.search.rebuild(self.source.source_id)
        second = self.search.search("来源", source_id=self.source.source_id)
        self.assertEqual(first["results"], second["results"])
        markdown = self.search.search(
            "安全", source_id=self.source.source_id, file_type=".md"
        )
        self.assertTrue(all(row["file_type"] == ".md" for row in markdown["results"]))

    def test_markdown_chunks_preserve_section_path_and_exact_offsets(self) -> None:
        result = self.search.search("拒绝符号链接", source_id=self.source.source_id)
        row = result["results"][0]
        self.assertEqual(row["section_path"], "安全设计")
        document = self.store.connection.execute(
            "SELECT content FROM documents WHERE document_id=?", (row["document_id"],)
        ).fetchone()
        extracted = document["content"][row["start_offset"] : row["end_offset"]]
        chunk = self.store.connection.execute(
            "SELECT content FROM lexical_chunks WHERE chunk_id=?", (row["chunk_id"],)
        ).fetchone()
        self.assertEqual(extracted, chunk["content"])

    def test_source_scope_prevents_cross_source_results(self) -> None:
        other = self.base / "other"
        other.mkdir()
        (other / "private.txt").write_text("禁止内容 独特词语", encoding="utf-8")
        ingestion = IngestionService(self.store)
        other_source = ingestion.register(other)
        ingestion.sync(other_source.source_id)
        self.search.rebuild(other_source.source_id)
        result = self.search.search("独特词语", source_id=self.source.source_id)
        self.assertEqual(result["results"], [])

    def test_evaluation_metrics(self) -> None:
        metrics = evaluate(
            self.search,
            [
                EvaluationQuery("只读授权目录", frozenset({"security.md"})),
                EvaluationQuery("BM25来源", frozenset({"search.txt"})),
            ],
            source_id=self.source.source_id,
        )
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["recall_at_10"], 1.0)
        self.assertEqual(metrics["mrr"], 1.0)
        self.assertEqual(metrics["forbidden_result_rate"], 0.0)
        self.assertGreaterEqual(metrics["p50_ms"], 0.0)
        self.assertGreaterEqual(metrics["p95_ms"], metrics["p50_ms"])

    def test_diagnosis_explains_semantic_miss(self) -> None:
        details = diagnose(
            self.search,
            [EvaluationQuery("断电续跑", frozenset({"security.md"}))],
            source_id=self.source.source_id,
        )
        self.assertIn(details[0]["category"], {"lexical_gap", "semantic_gap"})
        self.assertIsNone(details[0]["rank"])
