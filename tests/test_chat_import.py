from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mini_gl.chat_import import ChatImportService
from mini_gl.parsers.chat_json import parse_chat_export
from mini_gl.storage.sqlite import SQLiteStore


class ChatImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.path = self.base / "chat.json"
        self.db = self.base / "state.sqlite3"
        self.payload = {
            "schema_version": "1.0",
            "platform": "synthetic-chat",
            "conversation": {"id": "group-1", "title": "测试群", "participants": ["a", "b"]},
            "messages": [
                {
                    "id": "m1", "sender_id": "a", "sender_name": "同名",
                    "sent_at": "2026-01-01T09:00:00+08:00",
                    "message_type": "text", "text": "第一条",
                },
                {
                    "id": "m2", "sender_id": "b", "sender_name": "同名",
                    "sent_at": "2026-01-01T09:05:00+08:00", "message_type": "file",
                    "attachment_refs": ["attachment://report"], "reply_to": "m1",
                },
                {
                    "id": "m3", "sender_id": "a",
                    "sent_at": "2026-01-01T10:00:00+08:00",
                    "message_type": "text", "text": "不会保存", "withdrawn": True,
                },
            ],
        }
        self.path.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_parses_and_imports_idempotent_windows(self) -> None:
        parsed = parse_chat_export(self.path)
        self.assertEqual(len(parsed.messages), 3)
        self.assertIsNone(parsed.messages[-1].text)
        with SQLiteStore(self.db) as store:
            service = ChatImportService(store)
            first = service.import_file(self.path)
            second = service.import_file(self.path)
            self.assertEqual(first["documents"], 2)
            self.assertEqual(first["created"], 2)
            self.assertEqual(second["unchanged"], 2)
            rows = store.connection.execute(
                "SELECT content,metadata_json FROM documents ORDER BY created_at"
            ).fetchall()
            self.assertIn("附件引用", rows[0]["content"])
            self.assertIn("已撤回", rows[1]["content"])
            self.assertNotIn("不会保存", rows[1]["content"])
            metadata = json.loads(rows[0]["metadata_json"])
            self.assertEqual(metadata["conversation_id"], "group-1")
            self.assertEqual(metadata["participants"], ["a", "b"])

    def test_rejects_timezone_free_duplicate_and_external_reply(self) -> None:
        for mutation in ("timezone", "duplicate", "reply"):
            value = json.loads(json.dumps(self.payload))
            if mutation == "timezone":
                value["messages"][0]["sent_at"] = "2026-01-01T09:00:00"
            elif mutation == "duplicate":
                value["messages"][1]["id"] = "m1"
            else:
                value["messages"][1]["reply_to"] = "outside"
            self.path.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_chat_export(self.path)

    def test_rejects_unknown_schema_and_message_type(self) -> None:
        self.payload["schema_version"] = "2.0"
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "schema_version"):
            parse_chat_export(self.path)
        self.payload["schema_version"] = "1.0"
        self.payload["messages"][0]["message_type"] = "executable"
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "message_type"):
            parse_chat_export(self.path)
