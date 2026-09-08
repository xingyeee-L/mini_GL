from __future__ import annotations

import ast
import unittest
from pathlib import Path


class PrivacyAuditTests(unittest.TestCase):
    def test_source_tree_does_not_add_application_logging(self) -> None:
        source_root = Path(__file__).parents[1] / "src" / "mini_gl"
        offenders: list[str] = []
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    item.name == "logging" for item in node.names
                ):
                    offenders.append(str(path.relative_to(source_root)))
                if isinstance(node, ast.ImportFrom) and node.module == "logging":
                    offenders.append(str(path.relative_to(source_root)))
        self.assertEqual(offenders, [])

    def test_lock_files_contain_only_exact_package_pins(self) -> None:
        root = Path(__file__).parents[1]
        for name in ("requirements-dev.lock", "requirements-ml.lock"):
            lines = [
                line.strip()
                for line in (root / name).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            self.assertTrue(lines)
            self.assertTrue(all(line.count("==") == 1 for line in lines))
            self.assertTrue(all("://" not in line and "-e " not in line for line in lines))

    def test_log_artifacts_are_git_ignored(self) -> None:
        ignore = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.log", ignore.splitlines())
