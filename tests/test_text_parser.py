from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mini_gl.parsers.text import TextParseError, parse_text


class TextParserTests(unittest.TestCase):
    def test_supported_encodings_and_newlines(self) -> None:
        cases = {
            "utf8.txt": ("你好\r\nworld".encode(), "utf-8"),
            "utf8-bom.md": (b"\xef\xbb\xbfhello", "utf-8-sig"),
            "utf16le.txt": (b"\xff\xfe" + "你好".encode("utf-16-le"), "utf-16-le"),
            "utf16be.txt": (b"\xfe\xff" + "你好".encode("utf-16-be"), "utf-16-be"),
            "gb.txt": ("中文".encode("gb18030"), "gb18030"),
            "empty.txt": (b"", "utf-8"),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name, (raw, encoding) in cases.items():
                path = root / name
                path.write_bytes(raw)
                parsed = parse_text(path)
                self.assertEqual(parsed.encoding, encoding)
                self.assertEqual(parsed.content_hash, hashlib.sha256(raw).hexdigest())
            self.assertEqual(parse_text(root / "utf8.txt").content, "你好\nworld")

    def test_rejects_invalid_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.txt"
            path.write_bytes(b"\xff\xff\xff")
            with self.assertRaises(TextParseError):
                parse_text(path)

    def test_rejects_file_changed_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "moving.txt"
            path.write_text("stable bytes", encoding="utf-8")
            info = path.stat()
            changed = SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1,
            )
            with mock.patch("mini_gl.parsers.text.os.stat", side_effect=[info, changed]):
                with self.assertRaisesRegex(TextParseError, "changed"):
                    parse_text(path)
