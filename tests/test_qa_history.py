from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.storage.sqlite import SQLiteStore


class LocalQaHistoryTests(unittest.TestCase):
    def test_parallel_first_open_serializes_schema_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.sqlite3"

            def open_and_read() -> int:
                with SQLiteStore(database) as store:
                    return store.connection.execute("PRAGMA user_version").fetchone()[0]

            with ThreadPoolExecutor(max_workers=6) as pool:
                versions = list(pool.map(lambda _: open_and_read(), range(12)))
        self.assertEqual(versions, [13] * 12)

    def test_save_list_reopen_and_delete_one_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            database = base / "state.sqlite3"
            with SQLiteStore(database) as store:
                source = IngestionService(store).register(root)
                session_id = store.save_qa_turn(
                    session_id=None,
                    source_scope=source.source_id,
                    question="虚构项目的决定是什么？",
                    answer="决定采用本地索引。[来源 1]",
                    citations=[
                        {
                            "document_id": "local:test",
                            "chunk_id": "chunk-1",
                            "source_uri": "fictional.txt",
                            "title": "虚构资料",
                            "source_id": source.source_id,
                        }
                    ],
                    insufficient_evidence=False,
                    model="fake-local-model",
                    retrieval_ms=1.2,
                    generation_ms=2.3,
                    prompt_tokens=10,
                    completion_tokens=5,
                )
                store.save_qa_turn(
                    session_id=session_id,
                    source_scope="all",
                    question="还有别的结论吗？",
                    answer="证据不足。",
                    citations=[],
                    insufficient_evidence=True,
                    model=None,
                    retrieval_ms=0.5,
                    generation_ms=0,
                    prompt_tokens=None,
                    completion_tokens=None,
                )
                summaries = store.list_qa_sessions()
                self.assertEqual(summaries[0]["turn_count"], 2)
                self.assertNotIn("answer", summaries[0])

            with SQLiteStore(database) as reopened:
                session = reopened.get_qa_session(session_id)
                self.assertEqual(len(session["turns"]), 2)
                self.assertEqual(session["turns"][0]["citations"][0]["title"], "虚构资料")
                self.assertTrue(session["turns"][1]["insufficient_evidence"])
                removed = reopened.delete_qa_session(session_id)
                self.assertEqual(removed["turns"], 2)
                self.assertEqual(reopened.list_qa_sessions(), [])

    def test_delete_all_sessions_only_clears_local_qa_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            with SQLiteStore(base / "state.sqlite3") as store:
                source = IngestionService(store).register(root)
                for _ in range(2):
                    store.save_qa_turn(
                        session_id=None, source_scope=source.source_id,
                        question="测试问题", answer="证据不足", citations=[],
                        insufficient_evidence=True, model=None, retrieval_ms=0,
                        generation_ms=0, prompt_tokens=None, completion_tokens=None,
                    )
                removed = store.delete_all_qa_sessions()
                self.assertEqual(removed, {"sessions": 2, "turns": 2})
                self.assertEqual(store.list_qa_sessions(), [])
                self.assertEqual(store.get_source(source.source_id).source_id, source.source_id)

    def test_invalid_session_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteStore(Path(temporary) / "state.sqlite3") as store:
                with self.assertRaisesRegex(ValueError, "Invalid Q&A"):
                    store.get_qa_session("not-a-session")


if __name__ == "__main__":
    unittest.main()
