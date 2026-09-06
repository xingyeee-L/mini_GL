from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mini_gl.ingestion import IngestionService
from mini_gl.storage.sqlite import SQLiteStore
from mini_gl.web import make_server


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
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def _get_json(self, path: str) -> object:
        request = Request(  # noqa: S310 - fixed loopback URL
            self.base_url + path,
            headers={"X-Mini-GL-CSRF": self.server.csrf_token},
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            return json.load(response)

    def test_page_and_privacy_safe_file_status(self) -> None:
        with urlopen(self.base_url, timeout=2) as response:  # noqa: S310 - fixed loopback URL
            page = response.read().decode()
        self.assertIn("阶段 1 验收台", page)
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
