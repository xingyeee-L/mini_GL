from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mini_gl.security.paths import PathPolicy, PathPolicyError


class PathPolicyTests(unittest.TestCase):
    def test_allows_supported_file_inside_authorized_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "notes.md"
            source.write_text("synthetic notes", encoding="utf-8")
            policy = PathPolicy((root,), frozenset({".md", ".txt"}))

            self.assertEqual(policy.authorize(source), source.resolve())

    def test_rejects_sibling_directory_with_shared_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "allowed"
            sibling = base / "allowed-private"
            root.mkdir()
            sibling.mkdir()
            source = sibling / "secret.txt"
            source.write_text("synthetic secret", encoding="utf-8")
            policy = PathPolicy((root,), frozenset({".txt"}))

            with self.assertRaises(PathPolicyError):
                policy.authorize(source)

    def test_rejects_disallowed_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "script.exe"
            source.write_bytes(b"synthetic")
            policy = PathPolicy((root,), frozenset({".md", ".txt"}))

            with self.assertRaises(PathPolicyError):
                policy.authorize(source)

    def test_rejects_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "large.txt"
            source.write_bytes(b"12345")
            policy = PathPolicy((root,), frozenset({".txt"}), max_file_size=4)
            with self.assertRaises(PathPolicyError):
                policy.authorize(source)

    def test_rejects_excessive_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "one" / "two" / "notes.txt"
            source.parent.mkdir(parents=True)
            source.write_text("synthetic", encoding="utf-8")
            policy = PathPolicy((root,), frozenset({".txt"}), max_depth=1)
            with self.assertRaises(PathPolicyError):
                policy.authorize(source)

    def test_rejects_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.txt"
            link = root / "link.txt"
            target.write_text("synthetic", encoding="utf-8")
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("Creating symlinks is not permitted on this Windows installation")
            policy = PathPolicy((root,), frozenset({".txt"}))
            with self.assertRaises(PathPolicyError):
                policy.authorize(link)


if __name__ == "__main__":
    unittest.main()
