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
