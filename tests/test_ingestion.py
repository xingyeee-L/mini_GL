from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.connectors.base import ChangeKind
from mini_gl.ingestion import IngestionService
from mini_gl.parsers.text import TextParseError
from mini_gl.storage.sqlite import SQLiteStore


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.db = self.base / "state.sqlite3"
        self.store = SQLiteStore(self.db)
        self.service = IngestionService(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_full_change_lifecycle_and_source_preservation(self) -> None:
        note = self.root / "note.txt"
        page = self.root / "nested" / "page.md"
        page.parent.mkdir()
        note.write_text("one", encoding="utf-8")
        page.write_text("# page", encoding="utf-8")
        before = self._fingerprint(note)

        source = self.service.register(self.root)
        self.assertEqual(source.source_id, self.service.register(self.root).source_id)
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 2, "updated": 0, "unchanged": 0, "deleted": 0},
        )
        self.assertEqual(before, self._fingerprint(note))
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 0, "updated": 0, "unchanged": 2, "deleted": 0},
        )

        note.write_text("two", encoding="utf-8")
        page.unlink()
        added = self.root / "added.TXT"
        added.write_text("new", encoding="utf-8")
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 1, "updated": 1, "unchanged": 0, "deleted": 1},
        )
        status = self.store.status(source.source_id)[0]
        self.assertEqual(status["file_count"], 2)
        documents = self.store.connection.execute(
            "SELECT title,metadata_json FROM documents ORDER BY title"
        ).fetchall()
        self.assertEqual([row["title"] for row in documents], ["added.TXT", "note.txt"])
        self.assertTrue(
            all(
                json.loads(row["metadata_json"])["encoding"] == "utf-8"
                for row in documents
            )
        )

    def test_failed_scan_rolls_back_and_never_emits_delete(self) -> None:
        good = self.root / "good.txt"
        good.write_text("safe", encoding="utf-8")
        source = self.service.register(self.root)
        self.service.sync(source.source_id)
        good.unlink()
        (self.root / "broken.txt").write_bytes(b"\xff\xff\xff")

        with self.assertRaises(TextParseError):
            self.service.sync(source.source_id)

        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0], 1
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM change_events WHERE kind='deleted'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT status FROM sync_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()[0],
            "FAILED",
        )

    def test_interrupted_run_is_recovered(self) -> None:
        source = self.service.register(self.root)
        run_id = self.store.start_run(source.source_id)
        self.store.connection.execute(
            "INSERT INTO staged_files VALUES(?,?,?,?)", (run_id, "object", "x.txt", "hash")
        )
        self.store.connection.commit()
        self.store.close()
        self.store = SQLiteStore(self.db)
        self.service = IngestionService(self.store)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT status FROM sync_runs WHERE run_id=?", (run_id,)
            ).fetchone()[0],
            "ABORTED",
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM staged_files WHERE run_id=?", (run_id,)
            ).fetchone()[0],
            0,
        )

    def test_duplicate_event_application_is_idempotent(self) -> None:
        source = self.service.register(self.root)
        run_id = self.store.start_run(source.source_id)
        with self.store.connection:
            for _ in range(2):
                self.store._insert_event(
                    run_id,
                    source.source_id,
                    "same-object",
                    ChangeKind.CREATED,
                    "same-hash",
                    "2026-01-01T00:00:00+00:00",
                )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM change_events WHERE run_id=?", (run_id,)
            ).fetchone()[0],
            1,
        )

    @staticmethod
    def _fingerprint(path: Path) -> tuple[str, int, int]:
        info = path.stat()
        return hashlib.sha256(path.read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns
