from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mini_gl.product import product_status, uninstall_inventory


class DesktopProductTests(unittest.TestCase):
    def test_product_status_is_metadata_only_and_reports_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "start-mini-gl.cmd").write_text("launcher", encoding="utf-8")
            (root / "requirements-runtime.lock").write_text("locked", encoding="utf-8")
            data = root / "data"
            backups = data / "backups"
            backups.mkdir(parents=True)
            database = data / "mini_gl.sqlite3"
            database.write_bytes(b"synthetic-db")
            (backups / "mini-gl-synthetic.sqlite3").write_bytes(b"synthetic-backup")

            result = product_status(database, root)

            self.assertTrue(result["desktop_ready"])
            self.assertTrue(result["setup_complete"])
            self.assertEqual(result["backup_count"], 1)
            self.assertEqual(result["latest_backup"], "mini-gl-synthetic.sqlite3")

    def test_uninstall_inventory_never_lists_registered_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "data" / "mini_gl.sqlite3"
            external_source = root / "personal-source"
            external_source.mkdir()

            result = uninstall_inventory(database, root)
            paths = {str(item["path"]) for item in result["items"]}

            self.assertNotIn(str(external_source), paths)
            self.assertTrue(result["preserves_registered_sources"])
            self.assertEqual(result["confirmation"], "UNINSTALL MINI_GL")
