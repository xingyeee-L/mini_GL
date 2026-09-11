from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mini_gl.indexing.embeddings import DeterministicLocalEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.scheduler import AutoSyncScheduler, common_folder_candidates, next_run_time
from mini_gl.storage.sqlite import SQLiteStore


class AutoSyncSchedulerTests(unittest.TestCase):
    def test_common_folder_candidates_only_check_named_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "Documents").mkdir()
            (home / "Desktop").mkdir()
            candidates = {item["key"]: item for item in common_folder_candidates(home)}
            self.assertTrue(candidates["documents"]["available"])
            self.assertFalse(candidates["downloads"]["available"])
            self.assertTrue(candidates["desktop"]["available"])

    def test_due_source_runs_read_only_sync_and_incremental_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            note = root / "fictional.txt"
            note.write_text("虚构的自动同步资料", encoding="utf-8")
            original = note.read_bytes()
            database = base / "state.sqlite3"
            now = datetime.now(UTC)
            with SQLiteStore(database) as store:
                source = IngestionService(store).register(root)
                store.set_source_schedule(
                    source.source_id,
                    frequency="hourly",
                    enabled=True,
                    next_run_at=(now - timedelta(seconds=1)).isoformat(),
                )
            scheduler = AutoSyncScheduler(
                database,
                lambda: DeterministicLocalEmbedding(64),
                battery_check=lambda: False,
            )
            results = scheduler.run_due_once(now)
            self.assertEqual(results[0]["status"], "SUCCEEDED")
            self.assertEqual(note.read_bytes(), original)
            with SQLiteStore(database, recover_interrupted=False) as store:
                self.assertEqual(store.status(source.source_id)[0]["file_count"], 1)
                self.assertGreater(
                    store.connection.execute(
                        "SELECT COUNT(*) FROM lexical_chunks WHERE source_id=?",
                        (source.source_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertGreater(
                    store.connection.execute(
                        "SELECT COUNT(*) FROM vector_chunks WHERE source_id=?",
                        (source.source_id,),
                    ).fetchone()[0],
                    0,
                )
                schedule = store.get_source_schedule(source.source_id)
                self.assertEqual(schedule["last_status"], "SUCCEEDED")

    def test_battery_pause_skips_source_and_retries_later(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            (root / "fictional.txt").write_text("不会在电池上读取", encoding="utf-8")
            database = base / "state.sqlite3"
            now = datetime.now(UTC)
            with SQLiteStore(database) as store:
                source = IngestionService(store).register(root)
                store.set_source_schedule(
                    source.source_id,
                    frequency="hourly",
                    enabled=True,
                    pause_on_battery=True,
                    next_run_at=(now - timedelta(seconds=1)).isoformat(),
                )
            scheduler = AutoSyncScheduler(
                database,
                lambda: DeterministicLocalEmbedding(64),
                battery_check=lambda: True,
            )
            self.assertEqual(scheduler.run_due_once(now)[0]["status"], "SKIPPED")
            with SQLiteStore(database, recover_interrupted=False) as store:
                self.assertEqual(store.status(source.source_id)[0]["file_count"], 0)
                self.assertEqual(
                    store.get_source_schedule(source.source_id)["last_status"], "SKIPPED"
                )

    def test_next_run_time_rejects_unknown_frequency(self) -> None:
        self.assertIsNone(next_run_time("manual"))
        with self.assertRaisesRegex(ValueError, "frequency"):
            next_run_time("weekly")


if __name__ == "__main__":
    unittest.main()
