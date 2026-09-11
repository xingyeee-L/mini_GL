from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests._common_file_fixtures import write_pdf, write_xlsx
from tests._docx_fixture import write_docx

from mini_gl.generation.models import ChatResponse
from mini_gl.indexing.embeddings import DeterministicLocalEmbedding
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore
from mini_gl.web import make_server, resolve_document_path, source_preview


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

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
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
        self.assertIn("本地知识工作台", page)
        self.assertIn("今天想从你的知识库中", page)
        self.assertIn("真实 QQ/微信数据尚未开放", page)
        self.assertIn("构建 BGE 本地向量索引", page)
        self.assertIn("受控 Agent", page)
        self.assertIn("写入动作保持锁定", page)
        self.assertIn("选择文件夹", page)
        self.assertIn('id="register-root"', page)
        self.assertIn("首次运行检查", page)
        self.assertIn("Word DOCX", page)
        self.assertIn("PDF", page)
        self.assertIn("Excel XLSX", page)
        self.assertIn("PowerPoint PPTX", page)
        self.assertIn('/assets/app.css', page)
        self.assertIn('/assets/app.js', page)
        result = self._get_json(f"/api/source/{self.source_id}")
        encoded = json.dumps(result)
        self.assertIn("visible-name.txt", encoded)
        self.assertIn("created", encoded)
        self.assertNotIn("secret body", encoded)
        self.assertEqual(result["index"], {"lexical_chunks": 0, "vector_chunks": 0})

        runtime = self._get_json("/api/runtime")
        self.assertIn("127.0.0.1", str(runtime["network"]))
        self.assertIn("Qwen3", str(runtime["chat_model"]))

        with urlopen(self.base_url + "/assets/app.css", timeout=2) as response:  # noqa: S310
            self.assertIn(".home-hero", response.read().decode())
        with urlopen(self.base_url + "/assets/app.js", timeout=2) as response:  # noqa: S310
            script = response.read().decode()
            self.assertIn("runSearch", script)
            self.assertIn('value = "all"', script)

    def test_api_rejects_request_without_csrf_token(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base_url + "/api/sources", timeout=2)  # noqa: S310
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_real_source_registration_requires_explicit_authorization(self) -> None:
        another = self.base / "another-source"
        another.mkdir()
        with self.assertRaises(HTTPError) as caught:
            self._post_json("/api/register", {"root": str(another)})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        registered = self._post_json(
            "/api/register", {"root": str(another), "authorized": True}
        )
        self.assertTrue(registered["source_id"])

    def test_common_folders_require_per_selection_authorization_without_scanning(self) -> None:
        home = self.base / "profile"
        documents = home / "Documents"
        downloads = home / "Downloads"
        documents.mkdir(parents=True)
        downloads.mkdir()
        (documents / "not-yet-read.txt").write_text("deferred content", encoding="utf-8")
        self.server.common_home = home
        candidates = self._get_json("/api/common-folders")
        self.assertEqual(
            {item["key"] for item in candidates["folders"] if item["available"]},
            {"documents", "downloads"},
        )
        with self.assertRaises(HTTPError) as caught:
            self._post_json(
                "/api/register-common-folders",
                {"folders": ["documents"], "frequency": "hourly"},
            )
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        result = self._post_json(
            "/api/register-common-folders",
            {
                "folders": ["documents", "downloads"],
                "frequency": "hourly",
                "authorized": True,
            },
        )
        self.assertEqual(len(result["registered"]), 2)
        with SQLiteStore(self.db, recover_interrupted=False) as store:
            new_ids = [item["source_id"] for item in result["registered"]]
            self.assertTrue(
                all(store.status(str(source_id))[0]["file_count"] == 0 for source_id in new_ids)
            )
            self.assertTrue(
                all(
                    store.get_source_schedule(str(source_id))["frequency"] == "hourly"
                    for source_id in new_ids
                )
            )

    def test_native_directory_picker_only_returns_path_without_registering(self) -> None:
        selected = self.base / "selected-but-not-registered"
        selected.mkdir()
        self.server.directory_picker = lambda: selected
        picked = self._post_json("/api/pick-directory", {})
        self.assertEqual(picked, {"selected": True, "path": str(selected.resolve())})
        sources = self._get_json("/api/sources")
        self.assertEqual(len(sources), 1)

    def test_visual_docx_registration_sync_and_search_flow(self) -> None:
        root = self.base / "docx-source"
        root.mkdir()
        document = root / "fictional-brief.docx"
        write_docx(document)
        original_hash = hashlib.sha256(document.read_bytes()).hexdigest()
        registered = self._post_json(
            "/api/register", {"root": str(root), "authorized": True}
        )
        source_id = str(registered["source_id"])

        synced = self._post_json("/api/sync", {"source_id": source_id})
        self.assertEqual(synced["created"], 1)
        self._post_json("/api/index", {"source_id": source_id})
        result = self._get_json(
            f"/api/search?source_id={source_id}&q=fictional%20decision&file_type=.docx"
        )

        self.assertEqual(result["results"][0]["title"], document.name)
        self.assertEqual(
            hashlib.sha256(document.read_bytes()).hexdigest(), original_hash
        )

    def test_visual_pdf_and_xlsx_sync_index_and_filter_flow(self) -> None:
        root = self.base / "common-files-source"
        root.mkdir()
        pdf = root / "fictional-report.pdf"
        xlsx = root / "fictional-plan.xlsx"
        write_pdf(pdf)
        write_xlsx(xlsx)
        originals = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.iterdir()
        }
        registered = self._post_json(
            "/api/register", {"root": str(root), "authorized": True}
        )
        source_id = str(registered["source_id"])

        synced = self._post_json("/api/sync", {"source_id": source_id})
        self.assertEqual(synced["created"], 2)
        self._post_json("/api/index", {"source_id": source_id})
        pdf_result = self._get_json(
            f"/api/search?source_id={source_id}&q=fictional%20pdf&file_type=.pdf"
        )
        xlsx_result = self._get_json(
            f"/api/search?source_id={source_id}&q=spreadsheet%20decision&file_type=.xlsx"
        )

        self.assertEqual(pdf_result["results"][0]["title"], pdf.name)
        self.assertEqual(xlsx_result["results"][0]["title"], xlsx.name)
        self.assertEqual(
            originals,
            {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.iterdir()
            },
        )

    def test_runtime_diagnostics_and_visual_backup_restore(self) -> None:
        diagnostics = self._get_json("/api/diagnostics")
        self.assertEqual(diagnostics["database_integrity"], "ok")
        self.assertEqual(diagnostics["sources"], 1)
        self.assertIn("reachable", diagnostics["ollama"])
        self.assertIn("available", diagnostics["embedding"])
        self.assertTrue(diagnostics["document_formats"]["available"])
        self.assertEqual(diagnostics["document_formats"]["office_ooxml"], "built-in")

        backup = self.base / "backup.sqlite3"
        backup_result = self._post_json(
            "/api/backup", {"destination": str(backup)}
        )
        self.assertEqual(backup_result["integrity"], "ok")
        restored = self.base / "restored.sqlite3"
        restore_result = self._post_json(
            "/api/restore",
            {
                "backup": str(backup),
                "destination": str(restored),
                "confirmation": "RESTORE",
            },
        )
        self.assertEqual(restore_result["integrity"], "ok")
        managed = self._post_json("/api/managed-backup", {})
        self.assertEqual(managed["integrity"], "ok")
        listed = self._get_json("/api/backups")
        self.assertEqual(listed["backups"][0]["path"], managed["path"])

    def test_server_rejects_non_loopback_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_server(self.db, "0.0.0.0", 0)  # noqa: S104 - rejection test

    def test_server_rejects_a_second_instance_on_the_same_port(self) -> None:
        with self.assertRaises(OSError):
            make_server(self.db, port=self.server.server_port)

    def test_reveal_path_must_belong_to_current_snapshot(self) -> None:
        with SQLiteStore(self.db) as store:
            document_id = store.connection.execute(
                "SELECT document_id FROM documents WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
            resolved = resolve_document_path(store, self.source_id, document_id)
            self.assertEqual(resolved.name, "visible-name.txt")
            with self.assertRaisesRegex(ValueError, "current source snapshot"):
                resolve_document_path(store, self.source_id, "unknown-document")

    def test_source_preview_requires_current_snapshot_and_is_bounded(self) -> None:
        with SQLiteStore(self.db) as store:
            document_id = store.connection.execute(
                "SELECT document_id FROM documents WHERE source_id=?", (self.source_id,)
            ).fetchone()[0]
            preview = source_preview(store, self.source_id, document_id)
            self.assertEqual(preview["source_type"], "本地文件")
            self.assertEqual(preview["content"], "secret body")
            with self.assertRaisesRegex(ValueError, "authorized snapshot"):
                source_preview(store, self.source_id, "unknown-document")
        api_preview = self._post_json(
            "/api/source-preview",
            {"source_id": self.source_id, "document_id": document_id},
        )
        self.assertEqual(api_preview["title"], "visible-name.txt")

    def test_visual_hybrid_search_flow(self) -> None:
        body = {"source_id": self.source_id}
        self._post_json("/api/index", body)
        indexed = self._post_json("/api/vector-index", body)
        self.assertEqual(indexed["chunks"], 1)
        result = self._get_json(
            f"/api/hybrid-search?source_id={self.source_id}&q=secret%20body"
        )
        self.assertEqual(result["results"][0]["title"], "visible-name.txt")
        with SQLiteStore(self.db) as store:
            audit = store.connection.execute(
                "SELECT action,decision FROM agent_action_audit WHERE source_id=?",
                (self.source_id,),
            ).fetchall()
            self.assertIn(("search", "allow"), [(row[0], row[1]) for row in audit])

    def test_cross_source_lexical_search_is_authorized_per_source(self) -> None:
        second_root = self.base / "second-source"
        second_root.mkdir()
        (second_root / "other.txt").write_text("cross source phrase", encoding="utf-8")
        with SQLiteStore(self.db) as store:
            service = IngestionService(store)
            second = service.register(second_root)
            service.sync(second.source_id)
            LexicalSearchService(store).rebuild()
        result = self._get_json("/api/search?source_id=all&q=cross%20source%20phrase")
        self.assertEqual(result["results"][0]["title"], "other.txt")
        with SQLiteStore(self.db) as store:
            audited_sources = {
                row[0]
                for row in store.connection.execute(
                    "SELECT source_id FROM agent_action_audit WHERE action='search'"
                )
            }
        self.assertEqual(audited_sources, {self.source_id, second.source_id})

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
        session_id = str(result["session_id"])
        sessions = self._get_json("/api/qa-sessions")
        self.assertEqual(sessions["sessions"][0]["session_id"], session_id)
        self.assertEqual(sessions["sessions"][0]["turn_count"], 1)
        self.assertNotIn("secret body[", json.dumps(sessions, ensure_ascii=False))

        second = self._post_json(
            "/api/ask",
            {
                "source_id": self.source_id,
                "query": "secret body",
                "session_id": session_id,
            },
        )
        self.assertEqual(second["session_id"], session_id)
        history = self._get_json(f"/api/qa-session/{session_id}")
        self.assertEqual(len(history["turns"]), 2)

        with self.assertRaises(HTTPError) as caught:
            self._post_json(
                "/api/delete-qa-session",
                {"session_id": session_id, "confirmation": "wrong"},
            )
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        deleted = self._post_json(
            "/api/delete-qa-session",
            {"session_id": session_id, "confirmation": session_id[-8:]},
        )
        self.assertEqual(deleted["turns"], 2)

    def test_cross_source_answer_authorizes_and_preserves_citation_source(self) -> None:
        second_root = self.base / "answer-source"
        second_root.mkdir()
        (second_root / "second.txt").write_text(
            "secret body in a second source", encoding="utf-8"
        )
        with SQLiteStore(self.db) as store:
            service = IngestionService(store)
            second = service.register(second_root)
            service.sync(second.source_id)
            LexicalSearchService(store).rebuild()
            VectorSearchService(store, DeterministicLocalEmbedding(64)).rebuild()

        result = self._post_json(
            "/api/ask", {"source_id": "all", "query": "secret body"}
        )

        self.assertFalse(result["insufficient_evidence"])
        self.assertEqual(
            {citation["source_id"] for citation in result["citations"]},
            {self.source_id, second.source_id},
        )
        with SQLiteStore(self.db) as store:
            audited_sources = {
                row[0]
                for row in store.connection.execute(
                    "SELECT source_id FROM agent_action_audit WHERE action='answer'"
                )
            }
        self.assertEqual(audited_sources, {self.source_id, second.source_id})

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
        result = self._post_json(
            "/api/chat-import", {"path": str(chat), "authorized": True}
        )
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["documents"], 1)
        source_id = str(result["source_id"])
        with SQLiteStore(self.db) as store:
            document_id = store.connection.execute(
                "SELECT document_id FROM documents WHERE source_id=?", (source_id,)
            ).fetchone()[0]
            self.assertEqual(resolve_document_path(store, source_id, document_id), chat)
            preview = source_preview(store, source_id, document_id)
            self.assertEqual(preview["source_type"], "聊天记录")
            self.assertEqual(preview["conversation_id"], "chat-1")
            self.assertEqual(preview["participants"], ["a"])
            self.assertEqual(preview["timestamp_start"], "2026-01-01T09:00:00+08:00")
            self.assertIn("测试消息", str(preview["content"]))

    def test_visual_source_pause_and_confirmed_derived_delete(self) -> None:
        paused = self._post_json(
            "/api/source-pause", {"source_id": self.source_id, "paused": True}
        )
        self.assertTrue(paused["paused"])
        with self.assertRaises(HTTPError) as caught:
            self._post_json(
                "/api/delete-derived",
                {"source_id": self.source_id, "confirmation": "wrong"},
            )
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        deleted = self._post_json(
            "/api/delete-derived",
            {"source_id": self.source_id, "confirmation": self.source_id[-8:]},
        )
        self.assertEqual(deleted["documents"], 1)
        self.assertTrue((self.root / "visible-name.txt").exists())


class FakeChatModel:
    name = "fake-local-model"

    def generate(self, *, system_prompt: str, user_prompt: str) -> ChatResponse:
        return ChatResponse("secret body[来源 1]。", 12, 6)
