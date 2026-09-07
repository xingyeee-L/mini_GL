from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.maintenance import (
    DatabaseMaintenanceError,
    backup_database,
    restore_database,
)
from mini_gl.storage.sqlite import SQLiteStore


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_consistent_backup_and_restore_to_new_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "source"
            root.mkdir()
            (root / "fixture.txt").write_text("synthetic content", encoding="utf-8")
            database = base / "state.sqlite3"
            with SQLiteStore(database) as store:
                source = IngestionService(store).register(root)
                IngestionService(store).sync(source.source_id)
                backup = base / "backup.sqlite3"
                result = backup_database(database, backup)
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(len(str(result["sha256"])), 64)

            restored = base / "restored.sqlite3"
            restore = restore_database(backup, restored)
            self.assertEqual(restore["integrity"], "ok")
            with SQLiteStore(restored) as store:
                self.assertEqual(store.status(source.source_id)[0]["file_count"], 1)

    def test_restore_rejects_corruption_and_never_leaves_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            corrupt = base / "corrupt.sqlite3"
            corrupt.write_bytes(b"not a sqlite database")
            target = base / "restored.sqlite3"
            with self.assertRaisesRegex(DatabaseMaintenanceError, "valid SQLite"):
                restore_database(corrupt, target)
            self.assertFalse(target.exists())

    def test_backup_and_restore_never_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source.sqlite3"
            with SQLiteStore(source):
                pass
            occupied = base / "occupied.sqlite3"
            occupied.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(DatabaseMaintenanceError, "overwrite"):
                backup_database(source, occupied)
            self.assertEqual(occupied.read_text(encoding="utf-8"), "keep")
            with self.assertRaisesRegex(DatabaseMaintenanceError, "overwrite"):
                restore_database(source, occupied)
