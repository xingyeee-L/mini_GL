"""SQLite persistence for registered sources and atomic ingestion state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mini_gl.connectors.base import ChangeKind
from mini_gl.connectors.local_files import ScannedFile
from mini_gl.domain.models import SourceDocument


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_id: str
    root_path: Path
    max_file_size: int
    max_depth: int
    allowed_extensions: frozenset[str]
    paused: bool = False
    last_successful_run_id: str | None = None
    last_successful_at: str | None = None


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._migrate()
        self.recover_interrupted_runs()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 5:
            raise RuntimeError(f"Database schema {version} is newer than this application")
        if version == 0:
            self.connection.executescript(
                """
                CREATE TABLE sources (
                    source_id TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL UNIQUE,
                    allowed_extensions TEXT NOT NULL,
                    max_file_size INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_successful_run_id TEXT,
                    last_successful_at TEXT
                );
                CREATE TABLE sync_runs (
                    run_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    status TEXT NOT NULL
                        CHECK(status IN ('RUNNING','SUCCEEDED','FAILED','ABORTED')),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_type TEXT,
                    error_message TEXT
                );
                CREATE TABLE file_state (
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    document_id TEXT NOT NULL,
                    PRIMARY KEY(source_id, object_id),
                    UNIQUE(source_id, relative_path)
                );
                CREATE TABLE documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    access_scope TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(source_id, object_id)
                );
                CREATE TABLE change_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES sync_runs(run_id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content_hash TEXT,
                    observed_at TEXT NOT NULL,
                    UNIQUE(run_id, object_id, kind)
                );
                CREATE TABLE staged_files (
                    run_id TEXT NOT NULL REFERENCES sync_runs(run_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY(run_id, object_id)
                );
                PRAGMA user_version = 1;
                """
            )
            self.connection.commit()
            version = 1
        if version == 1:
            self.connection.executescript(
                """
                CREATE TABLE lexical_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    source_uri TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    updated_at TEXT,
                    content TEXT NOT NULL,
                    terms_json TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    UNIQUE(document_id, ordinal)
                );
                CREATE INDEX lexical_chunks_source_idx ON lexical_chunks(source_id);
                CREATE INDEX lexical_chunks_type_idx ON lexical_chunks(file_type);
                PRAGMA user_version = 2;
                """
            )
            self.connection.commit()
            version = 2
        if version == 2:
            self.connection.executescript(
                """
                CREATE TABLE vector_chunks (
                    chunk_id TEXT PRIMARY KEY
                        REFERENCES lexical_chunks(chunk_id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL
                );
                CREATE INDEX vector_chunks_source_idx ON vector_chunks(source_id);
                PRAGMA user_version = 3;
                """
            )
            self.connection.commit()
            version = 3
        if version == 3:
            self.connection.executescript(
                """
                CREATE TABLE vector_chunks_v4 (
                    chunk_id TEXT NOT NULL
                        REFERENCES lexical_chunks(chunk_id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY(chunk_id, provider)
                );
                INSERT INTO vector_chunks_v4
                    SELECT chunk_id,source_id,provider,dimension,vector FROM vector_chunks;
                DROP TABLE vector_chunks;
                ALTER TABLE vector_chunks_v4 RENAME TO vector_chunks;
                CREATE INDEX vector_chunks_source_idx ON vector_chunks(source_id, provider);
                PRAGMA user_version = 4;
                """
            )
            self.connection.commit()
            version = 4
        if version == 4:
            columns = {
                str(row["name"])
                for row in self.connection.execute("PRAGMA table_info(sources)").fetchall()
            }
            if "paused" not in columns:
                self.connection.execute(
                    "ALTER TABLE sources ADD COLUMN paused INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(paused IN (0,1))"
                )
            self.connection.execute("PRAGMA user_version = 5")
            self.connection.commit()

    def recover_interrupted_runs(self) -> int:
        with self.connection:
            rows = self.connection.execute(
                "SELECT run_id FROM sync_runs WHERE status = 'RUNNING'"
            ).fetchall()
            if rows:
                now = utc_now()
                self.connection.execute(
                    "UPDATE sync_runs SET status='ABORTED', finished_at=?, "
                    "error_type='InterruptedRun', error_message='Recovered after interruption' "
                    "WHERE status='RUNNING'",
                    (now,),
                )
                self.connection.executemany(
                    "DELETE FROM staged_files WHERE run_id=?", ((row["run_id"],) for row in rows)
                )
            return len(rows)

    def register_source(
        self,
        root: Path,
        max_file_size: int,
        max_depth: int,
        extensions: frozenset[str],
    ) -> RegisteredSource:
        root_text = str(root)
        existing = self.connection.execute(
            "SELECT * FROM sources WHERE root_path=?", (root_text,)
        ).fetchone()
        if existing is None:
            source_id = str(uuid.uuid4())
            with self.connection:
                self.connection.execute(
                    "INSERT INTO sources(source_id,root_path,allowed_extensions,max_file_size,"
                    "max_depth,created_at,last_successful_run_id,last_successful_at) "
                    "VALUES(?,?,?,?,?,?,NULL,NULL)",
                    (
                        source_id,
                        root_text,
                        json.dumps(sorted(extensions)),
                        max_file_size,
                        max_depth,
                        utc_now(),
                    ),
                )
        else:
            source_id = existing["source_id"]
        return self.get_source(source_id)

    def get_source(self, source_id: str) -> RegisteredSource:
        row = self.connection.execute(
            "SELECT * FROM sources WHERE source_id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown source: {source_id}")
        return RegisteredSource(
            source_id=row["source_id"],
            root_path=Path(row["root_path"]),
            max_file_size=row["max_file_size"],
            max_depth=row["max_depth"],
            allowed_extensions=frozenset(json.loads(row["allowed_extensions"])),
            paused=bool(row["paused"]),
            last_successful_run_id=row["last_successful_run_id"],
            last_successful_at=row["last_successful_at"],
        )

    def list_sources(self) -> list[RegisteredSource]:
        ids = self.connection.execute(
            "SELECT source_id FROM sources ORDER BY created_at"
        ).fetchall()
        return [self.get_source(row["source_id"]) for row in ids]

    def start_run(self, source_id: str) -> str:
        if self.get_source(source_id).paused:
            raise RuntimeError("Data source is paused")
        run_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                "INSERT INTO sync_runs(run_id,source_id,status,started_at) VALUES(?,?,'RUNNING',?)",
                (run_id, source_id, utc_now()),
            )
        return run_id

    def latest_recoverable_run(self, source_id: str) -> str | None:
        self.get_source(source_id)
        row = self.connection.execute(
            "SELECT run_id FROM sync_runs WHERE source_id=? AND status IN ('FAILED','ABORTED') "
            "ORDER BY started_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        return str(row["run_id"]) if row is not None else None

    def set_source_paused(self, source_id: str, paused: bool) -> RegisteredSource:
        self.get_source(source_id)
        with self.connection:
            self.connection.execute(
                "UPDATE sources SET paused=? WHERE source_id=?", (int(paused), source_id)
            )
        return self.get_source(source_id)

    def delete_derived_data(self, source_id: str) -> dict[str, int]:
        """Delete rebuildable application records while preserving the registered source."""
        self.get_source(source_id)
        counts = {
            "documents": self.connection.execute(
                "SELECT COUNT(*) FROM documents WHERE source_id=?", (source_id,)
            ).fetchone()[0],
            "lexical_chunks": self.connection.execute(
                "SELECT COUNT(*) FROM lexical_chunks WHERE source_id=?", (source_id,)
            ).fetchone()[0],
            "vector_chunks": self.connection.execute(
                "SELECT COUNT(*) FROM vector_chunks WHERE source_id=?", (source_id,)
            ).fetchone()[0],
        }
        with self.connection:
            self.connection.execute("DELETE FROM documents WHERE source_id=?", (source_id,))
            self.connection.execute("DELETE FROM file_state WHERE source_id=?", (source_id,))
            self.connection.execute("DELETE FROM sync_runs WHERE source_id=?", (source_id,))
            self.connection.execute(
                "UPDATE sources SET last_successful_run_id=NULL,last_successful_at=NULL "
                "WHERE source_id=?",
                (source_id,),
            )
        return counts

    def revoke_source(self, source_id: str) -> dict[str, int]:
        """Remove a registration and all application-owned records through foreign-key cascades."""
        self.get_source(source_id)
        counts = {
            "documents": self.connection.execute(
                "SELECT COUNT(*) FROM documents WHERE source_id=?", (source_id,)
            ).fetchone()[0],
            "lexical_chunks": self.connection.execute(
                "SELECT COUNT(*) FROM lexical_chunks WHERE source_id=?", (source_id,)
            ).fetchone()[0],
            "vector_chunks": self.connection.execute(
                "SELECT COUNT(*) FROM vector_chunks WHERE source_id=?", (source_id,)
            ).fetchone()[0],
            "sync_runs": self.connection.execute(
                "SELECT COUNT(*) FROM sync_runs WHERE source_id=?", (source_id,)
            ).fetchone()[0],
        }
        with self.connection:
            self.connection.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
        return counts

    def fail_run(self, run_id: str, error: Exception) -> None:
        message = str(error).replace("\n", " ")[:500]
        with self.connection:
            self.connection.execute("DELETE FROM staged_files WHERE run_id=?", (run_id,))
            self.connection.execute(
                "UPDATE sync_runs SET status='FAILED',finished_at=?,error_type=?,error_message=? "
                "WHERE run_id=? AND status='RUNNING'",
                (utc_now(), type(error).__name__, message, run_id),
            )

    @staticmethod
    def _document_values(document: SourceDocument) -> tuple[Any, ...]:
        return (
            document.id,
            document.source_uri,
            document.title,
            document.content,
            document.content_hash,
            document.access_scope,
            document.created_at.isoformat() if document.created_at else None,
            document.updated_at.isoformat() if document.updated_at else None,
            json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
        )

    def apply_scan(self, run_id: str, source_id: str, files: list[ScannedFile]) -> dict[str, int]:
        observed_at = utc_now()
        counts = {kind.value: 0 for kind in ChangeKind}
        with self.connection:
            run = self.connection.execute(
                "SELECT status FROM sync_runs WHERE run_id=? AND source_id=?", (run_id, source_id)
            ).fetchone()
            if run is None or run["status"] != "RUNNING":
                raise RuntimeError("Sync run is not active")
            self.connection.execute("DELETE FROM staged_files WHERE run_id=?", (run_id,))
            self.connection.executemany(
                "INSERT INTO staged_files VALUES(?,?,?,?)",
                ((run_id, f.object_id, f.relative_path, f.document.content_hash) for f in files),
            )
            previous = {
                row["object_id"]: row
                for row in self.connection.execute(
                    "SELECT * FROM file_state WHERE source_id=?", (source_id,)
                )
            }
            current_ids: set[str] = set()
            for item in files:
                current_ids.add(item.object_id)
                old = previous.get(item.object_id)
                if old is None:
                    kind = ChangeKind.CREATED
                elif old["content_hash"] == item.document.content_hash:
                    kind = ChangeKind.UNCHANGED
                else:
                    kind = ChangeKind.UPDATED
                counts[kind.value] += 1
                self._insert_event(
                    run_id,
                    source_id,
                    item.object_id,
                    kind,
                    item.document.content_hash,
                    observed_at,
                )
                values = self._document_values(item.document)
                self.connection.execute(
                    """INSERT INTO documents(
                    document_id,source_id,object_id,source_uri,title,content,
                    content_hash,access_scope,created_at,updated_at,metadata_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET
                    source_uri=excluded.source_uri,title=excluded.title,content=excluded.content,
                    content_hash=excluded.content_hash,access_scope=excluded.access_scope,
                    created_at=excluded.created_at,updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json""",
                    (values[0], source_id, item.object_id, *values[1:]),
                )
                self.connection.execute(
                    """INSERT INTO file_state VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(source_id,object_id) DO UPDATE SET
                    relative_path=excluded.relative_path,content_hash=excluded.content_hash,
                    size=excluded.size,mtime_ns=excluded.mtime_ns,document_id=excluded.document_id""",
                    (
                        source_id,
                        item.object_id,
                        item.relative_path,
                        item.document.content_hash,
                        item.size,
                        item.mtime_ns,
                        item.document.id,
                    ),
                )
            for object_id in previous.keys() - current_ids:
                counts[ChangeKind.DELETED.value] += 1
                self._insert_event(
                    run_id,
                    source_id,
                    object_id,
                    ChangeKind.DELETED,
                    None,
                    observed_at,
                )
                self.connection.execute(
                    "DELETE FROM documents WHERE source_id=? AND object_id=?",
                    (source_id, object_id),
                )
                self.connection.execute(
                    "DELETE FROM file_state WHERE source_id=? AND object_id=?",
                    (source_id, object_id),
                )
            self.connection.execute("DELETE FROM staged_files WHERE run_id=?", (run_id,))
            self.connection.execute(
                "UPDATE sync_runs SET status='SUCCEEDED',finished_at=? WHERE run_id=?",
                (observed_at, run_id),
            )
            self.connection.execute(
                "UPDATE sources SET last_successful_run_id=?,last_successful_at=? "
                "WHERE source_id=?",
                (run_id, observed_at, source_id),
            )
        return counts

    def _insert_event(
        self,
        run_id: str,
        source_id: str,
        object_id: str,
        kind: ChangeKind,
        content_hash: str | None,
        observed_at: str,
    ) -> None:
        payload = f"{run_id}\0{source_id}\0{object_id}\0{kind.value}\0{content_hash or ''}"
        event_id = hashlib.sha256(payload.encode()).hexdigest()
        self.connection.execute(
            "INSERT OR IGNORE INTO change_events VALUES(?,?,?,?,?,?,?)",
            (event_id, run_id, source_id, object_id, kind.value, content_hash, observed_at),
        )

    def status(self, source_id: str | None = None) -> list[dict[str, Any]]:
        sources = [self.get_source(source_id)] if source_id else self.list_sources()
        result: list[dict[str, Any]] = []
        for source in sources:
            latest = self.connection.execute(
                "SELECT status,started_at,finished_at,error_type,error_message FROM sync_runs "
                "WHERE source_id=? ORDER BY started_at DESC LIMIT 1",
                (source.source_id,),
            ).fetchone()
            count = self.connection.execute(
                "SELECT COUNT(*) FROM file_state WHERE source_id=?", (source.source_id,)
            ).fetchone()[0]
            item = asdict(source)
            item["root_path"] = str(source.root_path)
            item["allowed_extensions"] = sorted(source.allowed_extensions)
            item["file_count"] = count
            item["latest_run"] = dict(latest) if latest else None
            result.append(item)
        return result

    def file_status(self, source_id: str) -> list[dict[str, Any]]:
        """Return privacy-safe file metadata without document content."""
        rows = self.connection.execute(
            "SELECT object_id,relative_path,content_hash,size,mtime_ns FROM file_state "
            "WHERE source_id=? ORDER BY relative_path COLLATE NOCASE",
            (source_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_events(self, source_id: str) -> list[dict[str, Any]]:
        """Return events from the latest completed run without document content."""
        run = self.connection.execute(
            "SELECT run_id,status,started_at,finished_at,error_type,error_message "
            "FROM sync_runs WHERE source_id=? ORDER BY started_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if run is None:
            return []
        rows = self.connection.execute(
            "SELECT e.kind,e.object_id,e.observed_at,f.relative_path "
            "FROM change_events e LEFT JOIN file_state f "
            "ON f.source_id=e.source_id AND f.object_id=e.object_id "
            "WHERE e.run_id=? ORDER BY COALESCE(f.relative_path,e.object_id) COLLATE NOCASE",
            (run["run_id"],),
        ).fetchall()
        return [dict(row) for row in rows]
