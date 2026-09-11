from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests._common_file_fixtures import write_pdf, write_pptx, write_xlsx
from tests._docx_fixture import write_docx

from mini_gl.connectors.base import ChangeKind
from mini_gl.ingestion import DEFAULT_EXTENSIONS, IngestionService
from mini_gl.parsers.docx import DocxParseError
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

    def test_docx_change_lifecycle_uses_the_same_atomic_source_pipeline(self) -> None:
        document = self.root / "brief.docx"
        write_docx(document)
        original = self._fingerprint(document)
        source = self.service.register(self.root)

        self.assertIn(".docx", source.allowed_extensions)
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 1, "updated": 0, "unchanged": 0, "deleted": 0},
        )
        self.assertEqual(self._fingerprint(document), original)
        row = self.store.connection.execute(
            "SELECT title,content,metadata_json FROM documents WHERE source_id=?",
            (source.source_id,),
        ).fetchone()
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(row["title"], "brief.docx")
        self.assertEqual(row["content"], "fictional project decision")
        self.assertEqual(metadata["parser"], "docx-ooxml-v1")

        write_docx(
            document,
            document=(
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
                b'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                b"<w:t>revised fictional decision</w:t></w:r></w:p></w:body>"
                b"</w:document>"
            ),
        )
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 0, "updated": 1, "unchanged": 0, "deleted": 0},
        )
        document.unlink()
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 0, "updated": 0, "unchanged": 0, "deleted": 1},
        )

    def test_common_formats_share_the_atomic_source_pipeline(self) -> None:
        write_xlsx(self.root / "plan.xlsx")
        write_pptx(self.root / "briefing.pptx")
        write_pdf(self.root / "report.pdf")
        (self.root / "table.csv").write_text(
            "topic,value\nfictional csv decision,42", encoding="utf-8"
        )
        (self.root / "page.html").write_text(
            "<h1>fictional HTML decision</h1>", encoding="utf-8"
        )
        (self.root / "config.toml").write_text(
            'decision = "fictional config"', encoding="utf-8"
        )
        originals = {
            path.name: self._fingerprint(path)
            for path in self.root.iterdir()
            if path.is_file()
        }

        source = self.service.register(self.root)
        self.assertEqual(
            self.service.sync(source.source_id),
            {"created": 6, "updated": 0, "unchanged": 0, "deleted": 0},
        )
        rows = self.store.connection.execute(
            "SELECT title,content,metadata_json FROM documents ORDER BY title"
        ).fetchall()
        parsers = {
            row["title"]: json.loads(row["metadata_json"])["parser"] for row in rows
        }
        self.assertEqual(parsers["plan.xlsx"], "xlsx-ooxml-v1")
        self.assertEqual(parsers["briefing.pptx"], "pptx-ooxml-v1")
        self.assertEqual(parsers["report.pdf"], "pdf-pypdf-v1")
        self.assertTrue(any("fictional pdf decision" in row["content"] for row in rows))
        self.assertEqual(
            originals,
            {
                path.name: self._fingerprint(path)
                for path in self.root.iterdir()
                if path.is_file()
            },
        )

    def test_explicit_reregistration_adds_supported_formats_without_widening_limits(
        self,
    ) -> None:
        old = self.store.register_source(
            self.root, 1_024, 2, frozenset({".txt", ".md"})
        )

        upgraded = self.service.register(self.root)

        self.assertEqual(upgraded.source_id, old.source_id)
        self.assertEqual(upgraded.allowed_extensions, DEFAULT_EXTENSIONS)
        self.assertEqual(upgraded.max_file_size, 1_024)
        self.assertEqual(upgraded.max_depth, 2)

    def test_unsafe_docx_rolls_back_without_false_deletions(self) -> None:
        original = self.root / "keep.txt"
        original.write_text("fictional stable content", encoding="utf-8")
        source = self.service.register(self.root)
        self.service.sync(source.source_id)
        original.unlink()
        unsafe = self.root / "unsafe.docx"
        write_docx(
            unsafe,
            document=(
                b'<!DOCTYPE w:document [<!ENTITY x "expanded">]>'
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
                b'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&x;</w:t>'
                b"</w:r></w:p></w:body></w:document>"
            ),
        )

        with self.assertRaises(DocxParseError):
            self.service.sync(source.source_id)

        self.assertEqual(self.store.status(source.source_id)[0]["file_count"], 1)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM change_events WHERE kind='deleted'"
            ).fetchone()[0],
            0,
        )

    def test_unsupported_encoding_is_quarantined_without_losing_prior_snapshot(self) -> None:
        good = self.root / "good.txt"
        good.write_text("safe", encoding="utf-8")
        source = self.service.register(self.root)
        self.service.sync(source.source_id)
        good.write_bytes(b"\xff\xff\xff")
        added = self.root / "added.md"
        added.write_text("# usable", encoding="utf-8")

        result = self.service.sync(source.source_id)

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(
            result["warnings"],
            [{"relative_path": "good.txt", "reason": "unsupported_text_encoding"}],
        )
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0], 2
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
            "SUCCEEDED",
        )
        stored = self.store.connection.execute(
            "SELECT content FROM documents WHERE title='good.txt'"
        ).fetchone()[0]
        self.assertEqual(stored, "safe")

    def test_deep_subtree_is_skipped_without_false_deleting_its_snapshot(self) -> None:
        deep = self.root / "level-one" / "level-two"
        deep.mkdir(parents=True)
        document = deep / "deep.txt"
        document.write_text("retained deep content", encoding="utf-8")
        source = self.service.register(self.root, max_depth=2)
        self.service.sync(source.source_id)
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE sources SET max_depth=1 WHERE source_id=?", (source.source_id,)
            )

        result = self.service.sync(source.source_id)

        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(
            result["warnings"],
            [
                {
                    "relative_path": "level-one/level-two",
                    "reason": "maximum_recursion_depth",
                }
            ],
        )
        self.assertEqual(self.store.status(source.source_id)[0]["file_count"], 1)

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

    def test_fault_after_scan_rolls_back_and_resume_restarts_from_committed_snapshot(self) -> None:
        note = self.root / "note.txt"
        note.write_text("version one", encoding="utf-8")
        source = self.service.register(self.root)
        self.service.sync(source.source_id)
        note.write_text("version two", encoding="utf-8")
        (self.root / "added.txt").write_text("new", encoding="utf-8")

        def interrupt() -> None:
            raise RuntimeError("deterministic injected interruption")

        with self.assertRaisesRegex(RuntimeError, "injected interruption"):
            self.service.sync(source.source_id, after_scan=interrupt)
        row = self.store.connection.execute(
            "SELECT content FROM documents WHERE source_id=? AND title='note.txt'",
            (source.source_id,),
        ).fetchone()
        self.assertEqual(row["content"], "version one")
        self.assertEqual(self.store.status(source.source_id)[0]["file_count"], 1)

        resumed = self.service.resume(source.source_id)
        self.assertEqual(resumed["updated"], 1)
        self.assertEqual(resumed["created"], 1)
        self.assertEqual(self.store.status(source.source_id)[0]["file_count"], 2)
        self.assertIsNotNone(resumed["resumed_from_run_id"])

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

    def test_pause_and_delete_derived_data_preserve_source_files(self) -> None:
        note = self.root / "keep.txt"
        note.write_text("keep me", encoding="utf-8")
        source = self.service.register(self.root)
        self.service.sync(source.source_id)
        self.store.set_source_paused(source.source_id, True)
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.service.sync(source.source_id)
        self.store.set_source_paused(source.source_id, False)
        removed = self.store.delete_derived_data(source.source_id)
        self.assertEqual(removed["documents"], 1)
        self.assertTrue(note.exists())
        self.assertEqual(note.read_text(encoding="utf-8"), "keep me")
        self.assertEqual(self.store.status(source.source_id)[0]["file_count"], 0)

    def test_partial_pause_migration_recovers_idempotently(self) -> None:
        self.store.close()
        connection = sqlite3.connect(self.db)
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
        connection.close()
        self.store = SQLiteStore(self.db)
        self.service = IngestionService(self.store)
        self.assertEqual(
            self.store.connection.execute("PRAGMA user_version").fetchone()[0], 11
        )

    @staticmethod
    def _fingerprint(path: Path) -> tuple[str, int, int]:
        info = path.stat()
        return hashlib.sha256(path.read_bytes()).hexdigest(), info.st_size, info.st_mtime_ns
