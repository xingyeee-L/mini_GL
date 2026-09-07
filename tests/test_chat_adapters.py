from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.adapters import convert_export
from mini_gl.parsers.chat_json import parse_chat_export


class ChatAdapterTests(unittest.TestCase):
    def test_synthetic_qq_and_wechat_convert_to_neutral_schema(self) -> None:
        fixtures = Path(__file__).parent / "fixtures" / "synthetic"
        with tempfile.TemporaryDirectory() as directory:
            for kind in ("qq", "wechat"):
                destination = Path(directory) / f"{kind}-neutral.json"
                result = convert_export(kind, fixtures / f"{kind}_export.json", destination)
                parsed = parse_chat_export(destination)
                self.assertEqual(result["messages"], 2)
                self.assertEqual(len(parsed.messages), 2)
                self.assertEqual(parsed.platform, f"{kind}-export")
            wechat = json.loads(
                (Path(directory) / "wechat-neutral.json").read_text(encoding="utf-8")
            )
            self.assertTrue(wechat["messages"][1]["withdrawn"])

    def test_converter_refuses_to_overwrite_output(self) -> None:
        fixtures = Path(__file__).parent / "fixtures" / "synthetic"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "exists.json"
            destination.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                convert_export("qq", fixtures / "qq_export.json", destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep")
