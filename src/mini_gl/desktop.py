"""Local desktop readiness checks without cloud access or document reads."""

from __future__ import annotations

import http.client
import json
import platform
import sqlite3
from pathlib import Path

from mini_gl.indexing.embeddings import BGE_DEFAULT_PATH
from mini_gl.storage.sqlite import SQLiteStore


def pick_directory() -> Path | None:
    """Open the OS folder chooser without reading the selected directory."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("Python Tk support is required for the folder picker") from exc

    root: tk.Tk | None = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            title="选择要授权给 mini_GL 的资料目录",
            mustexist=True,
        )
        return Path(selected) if selected else None
    except tk.TclError as exc:
        raise RuntimeError("The native folder picker is unavailable") from exc
    finally:
        if root is not None:
            root.destroy()


def runtime_diagnostics(store: SQLiteStore, database: Path) -> dict[str, object]:
    """Return metadata-only health signals for the local workspace."""
    integrity = store.connection.execute("PRAGMA quick_check").fetchone()[0]
    source_count = store.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    document_count = store.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    lexical_count = store.connection.execute("SELECT COUNT(*) FROM lexical_chunks").fetchone()[0]
    vector_count = store.connection.execute("SELECT COUNT(*) FROM vector_chunks").fetchone()[0]
    model = _ollama_health()
    embedding_path = BGE_DEFAULT_PATH.resolve()
    embedding = {
        "available": embedding_path.is_dir(),
        "model": "BAAI/bge-small-zh-v1.5",
        "path": str(embedding_path),
    }
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "database_integrity": integrity,
        "database_size": database.stat().st_size if database.exists() else 0,
        "sources": source_count,
        "documents": document_count,
        "lexical_chunks": lexical_count,
        "vector_chunks": vector_count,
        "ollama": model,
        "embedding": embedding,
        "ready": (
            integrity == "ok"
            and bool(model["reachable"])
            and bool(model["model_available"])
            and bool(embedding["available"])
        ),
    }


def _ollama_health() -> dict[str, object]:
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=1.5)
    try:
        connection.request("GET", "/api/tags", headers={"Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(256_000)
        if response.status != 200:
            return {"reachable": False, "model_available": False, "status": response.status}
        payload = json.loads(raw)
        names = {
            str(model.get("name", ""))
            for model in payload.get("models", [])
            if isinstance(model, dict)
        }
        expected = "qwen3:4b-instruct-2507-q4_K_M"
        return {
            "reachable": True,
            "model_available": expected in names,
            "model": expected,
        }
    except (OSError, json.JSONDecodeError):
        return {
            "reachable": False,
            "model_available": False,
            "model": "qwen3:4b-instruct-2507-q4_K_M",
        }
    finally:
        connection.close()
