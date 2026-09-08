from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.cli import main


class CliTests(unittest.TestCase):
    def test_register_sync_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "source"
            root.mkdir()
            (root / "hello.txt").write_text("hello", encoding="utf-8")
            db = base / "state.sqlite3"

            code, registered = self._invoke("register", str(root), "--db", str(db))
            self.assertEqual(code, 0)
            source_id = json.loads(registered)["source_id"]
            code, synced = self._invoke("sync", source_id, "--db", str(db))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(synced)["created"], 1)
            code, status = self._invoke("status", source_id, "--db", str(db))
            self.assertEqual(code, 0)
            payload = json.loads(status)
            self.assertEqual(payload[0]["file_count"], 1)
            self.assertNotIn("hello", status)
            code, indexed = self._invoke("index", source_id, "--db", str(db))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(indexed)["chunks"], 1)
            code, searched = self._invoke("search", "hello", "--db", str(db))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(searched)["results"][0]["title"], "hello.txt")

            backup = base / "backup.sqlite3"
            code, backed_up = self._invoke("backup", str(backup), "--db", str(db))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(backed_up)["integrity"], "ok")
            restored = base / "restored.sqlite3"
            code, restored_output = self._invoke("restore", str(backup), str(restored))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(restored_output)["integrity"], "ok")
            code, restored_status = self._invoke("status", source_id, "--db", str(restored))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(restored_status)[0]["file_count"], 1)

            original = (root / "hello.txt").read_bytes()
            code, rejected = self._invoke(
                "revoke", source_id, "--confirm", "wrong", "--db", str(restored)
            )
            self.assertEqual(code, 1)
            self.assertIn("Confirmation", json.loads(rejected)["message"])
            code, revoked = self._invoke(
                "revoke", source_id, "--confirm", source_id[-8:], "--db", str(restored)
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(revoked)["documents"], 1)
            self.assertEqual((root / "hello.txt").read_bytes(), original)
            code, empty = self._invoke("status", "--db", str(restored))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(empty), [])

    def test_synthetic_benchmark_cli(self) -> None:
        code, output = self._invoke(
            "benchmark-ingestion", "--files", "10", "--file-size", "128"
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["files"], 10)
        self.assertTrue(payload["source_unchanged"])

    def test_rejects_limits_above_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "source"
            root.mkdir()
            code, output = self._invoke(
                "register", str(root), "--max-depth", "9", "--db", str(Path(temp_dir) / "db")
            )
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)["error"], "PathPolicyError")

    @staticmethod
    def _invoke(*args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, output.getvalue()
