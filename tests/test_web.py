from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mini_gl.generation.models import ChatResponse
from mini_gl.indexing.embeddings import DeterministicLocalEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.storage.sqlite import SQLiteStore
from mini_gl.web import make_server, resolve_document_path


class WebAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "visible-name.txt").write_text("secret body", encoding="utf-8")
        self.db = self.base / "state.sqlite3"
        with SQLiteStore(self.db) as store:
            service = IngestionService(store)
            source = service.register(self.root)
            service.sync(source.source_id)
            self.source_id = source.source_id
        self.server = make_server(self.db, port=0)
        self.server.embedding_provider = DeterministicLocalEmbedding(64)
        self.server.chat_model = FakeChatModel()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def _get_json(self, path: str) -> dict[str, object]:
        request = Request(  # noqa: S310 - fixed loopback URL
            self.base_url + path,
            headers={"X-Mini-GL-CSRF": self.server.csrf_token},
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            return json.load(response)  # type: ignore[no-any-return]

    def _post_json(self, path: str, body: dict[str, str]) -> dict[str, object]:
        request = Request(  # noqa: S310 - fixed loopback URL
            self.base_url + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"X-Mini-GL-CSRF": self.server.csrf_token},
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            return json.load(response)  # type: ignore[no-any-return]

    def test_page_and_privacy_safe_file_status(self) -> None:
        with urlopen(self.base_url, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            page = response.read().decode()
        self.assertIn("本地数据与搜索验收台", page)
        self.assertIn("构建 BGE 本地向量索引", page)
        result = self._get_json(f"/api/source/{self.source_id}")
        encoded = json.dumps(result)
        self.assertIn("visible-name.txt", encoded)
        self.assertIn("created", encoded)
        self.assertNotIn("secret body", encoded)

    def test_api_rejects_request_without_csrf_token(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/api/sources", timeout=2)  # noqa: S310
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_server_rejects_non_loopback_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_server(self.db, "0.0.0.0", 0)  # noqa: S104 - rejection test

    def test_reveal_path_must_belong_to_current_snapshot(self) -> None:
        with SQLiteStore(self.db) as store:
            document_id = store.connection.execute(
                "SELECT document_id FROM documents WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
            resolved = resolve_document_path(store, self.source_id, document_id)
            self.assertEqual(resolved.name, "visible-name.txt")
            with self.assertRaisesRegex(ValueError, "current source snapshot"):
                resolve_document_path(store, self.source_id, "unknown-document")

    def test_visual_hybrid_search_flow(self) -> None:
        body = {"source_id": self.source_id}
        self._post_json("/api/index", body)
        indexed = self._post_json("/api/vector-index", body)
        self.assertEqual(indexed["chunks"], 1)
        result = self._get_json(
            f"/api/hybrid-search?source_id={self.source_id}&q=secret%20body"
        )
        self.assertEqual(result["results"][0]["title"], "visible-name.txt")

    def test_visual_grounded_answer_flow(self) -> None:
        body = {"source_id": self.source_id}
        self._post_json("/api/index", body)
        self._post_json("/api/vector-index", body)
        result = self._post_json(
            "/api/ask", {"source_id": self.source_id, "query": "secret body"}
        )
        self.assertEqual(result["answer"], "secret body[来源 1]。")
        self.assertFalse(result["insufficient_evidence"])
        self.assertEqual(result["citations"][0]["title"], "visible-name.txt")
        self.assertEqual(result["prompt_tokens"], 12)

    def test_visual_neutral_chat_import_flow(self) -> None:
        chat = self.base / "neutral-chat.json"
        chat.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "platform": "synthetic-chat",
                    "conversation": {
                        "id": "chat-1", "title": "虚构聊天", "participants": ["a"]
                    },
                    "messages": [
                        {
                            "id": "m1", "sender_id": "a",
                            "sent_at": "2026-01-01T09:00:00+08:00",
                            "message_type": "text", "text": "测试消息",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = self._post_json("/api/chat-import", {"path": str(chat)})
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["documents"], 1)
        source_id = str(result["source_id"])
        with SQLiteStore(self.db) as store:
            document_id = store.connection.execute(
                "SELECT document_id FROM documents WHERE source_id=?", (source_id,)
            ).fetchone()[0]
            self.assertEqual(resolve_document_path(store, source_id, document_id), chat)


class FakeChatModel:
    name = "fake-local-model"

    def generate(self, *, system_prompt: str, user_prompt: str) -> ChatResponse:
        return ChatResponse("secret body[来源 1]。", 12, 6)
