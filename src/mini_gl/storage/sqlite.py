"""SQLite persistence for registered sources and atomic ingestion state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mini_gl.connectors.base import ChangeKind
from mini_gl.connectors.local_files import ScannedFile
from mini_gl.domain.models import SourceDocument

_MIGRATION_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_id: str
    root_path: Path
    max_file_size: int
    max_depth: int
    allowed_extensions: frozenset[str]
    source_type: str = "local_files"
    paused: bool = False
    last_successful_run_id: str | None = None
    last_successful_at: str | None = None


class SQLiteStore:
    def __init__(self, path: Path, *, recover_interrupted: bool = True) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with _MIGRATION_LOCK:
                self.connection.execute("PRAGMA foreign_keys = ON")
                self.connection.execute("PRAGMA journal_mode = WAL")
                self._migrate()
            if recover_interrupted:
                self.recover_interrupted_runs()
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 11:
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
            version = 5
        if version == 5:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_action_audit (
                    event_id TEXT PRIMARY KEY,
                    idempotency_key TEXT,
                    action TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(idempotency_key, action, source_id)
                );
                PRAGMA user_version = 6;
                """
            )
            self.connection.commit()
            version = 6
        if version == 6:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_action_workflows (
                    workflow_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    state TEXT NOT NULL,
                    confirmation_hash TEXT,
                    confirmation_expires_at TEXT,
                    failure_code TEXT,
                    compensation_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(idempotency_key, action, source_id)
                );
                PRAGMA user_version = 7;
                """
            )
            self.connection.commit()
            version = 7
        if version == 7:
            self.connection.execute("PRAGMA foreign_keys = OFF")
            self.connection.executescript(
                """
                CREATE TABLE agent_action_audit_v8 (
                    event_id TEXT PRIMARY KEY,
                    idempotency_key TEXT,
                    action TEXT NOT NULL,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    decision TEXT NOT NULL
                        CHECK(decision IN ('allow','require_confirmation','deny')),
                    risk TEXT NOT NULL CHECK(risk IN ('read_only','reversible','destructive')),
                    reason_code TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO agent_action_audit_v8
                    SELECT a.event_id,a.idempotency_key,a.action,a.source_id,a.decision,a.risk,
                           a.reason_code,a.created_at
                    FROM agent_action_audit a JOIN sources s ON s.source_id=a.source_id;
                DROP TABLE agent_action_audit;
                ALTER TABLE agent_action_audit_v8 RENAME TO agent_action_audit;
                CREATE INDEX agent_action_audit_operation_idx
                    ON agent_action_audit(idempotency_key,action,source_id);

                CREATE TABLE agent_action_workflows_v8 (
                    workflow_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                    risk TEXT NOT NULL CHECK(risk IN ('reversible','destructive')),
                    state TEXT NOT NULL CHECK(state IN (
                        'awaiting_confirmation','ready','simulating','succeeded','failed','compensated'
                    )),
                    confirmation_hash TEXT,
                    confirmation_expires_at TEXT,
                    failure_code TEXT,
                    compensation_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(idempotency_key, action, source_id)
                );
                INSERT INTO agent_action_workflows_v8
                    SELECT w.workflow_id,w.idempotency_key,w.action,w.source_id,w.risk,w.state,
                           w.confirmation_hash,w.confirmation_expires_at,w.failure_code,
                           w.compensation_code,w.created_at,w.updated_at
                    FROM agent_action_workflows w JOIN sources s ON s.source_id=w.source_id;
                DROP TABLE agent_action_workflows;
                ALTER TABLE agent_action_workflows_v8 RENAME TO agent_action_workflows;
                PRAGMA user_version = 8;
                """
            )
            self.connection.commit()
            self.connection.execute("PRAGMA foreign_keys = ON")
            version = 8
        if version == 8:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS qa_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qa_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL
                        REFERENCES qa_sessions(session_id) ON DELETE CASCADE,
                    source_scope TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    insufficient_evidence INTEGER NOT NULL
                        CHECK(insufficient_evidence IN (0,1)),
                    model TEXT,
                    retrieval_ms REAL NOT NULL,
                    generation_ms REAL NOT NULL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS qa_turns_session_idx
                    ON qa_turns(session_id, created_at, turn_id);
                PRAGMA user_version = 9;
                """
            )
            self.connection.commit()
            version = 9
        if version == 9:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_schedules (
                    source_id TEXT PRIMARY KEY
                        REFERENCES sources(source_id) ON DELETE CASCADE,
                    frequency TEXT NOT NULL
                        CHECK(frequency IN ('manual','hourly','daily')),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    pause_on_battery INTEGER NOT NULL CHECK(pause_on_battery IN (0,1)),
                    auto_lexical INTEGER NOT NULL CHECK(auto_lexical IN (0,1)),
                    auto_vector INTEGER NOT NULL CHECK(auto_vector IN (0,1)),
                    next_run_at TEXT,
                    last_started_at TEXT,
                    last_finished_at TEXT,
                    last_status TEXT CHECK(last_status IN ('SUCCEEDED','FAILED','SKIPPED')),
                    last_error TEXT
                );
                UPDATE sync_runs SET
                    status='ABORTED',
                    finished_at=COALESCE(finished_at, datetime('now')),
                    error_type=COALESCE(error_type, 'InterruptedRun'),
                    error_message=COALESCE(error_message, 'Recovered during scheduler migration')
                WHERE status='RUNNING';
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_sync_per_source
                    ON sync_runs(source_id) WHERE status='RUNNING';
                PRAGMA user_version = 10;
                """
            )
            self.connection.commit()
            version = 10
        if version == 10:
            columns = {
                str(row["name"])
                for row in self.connection.execute("PRAGMA table_info(sources)").fetchall()
            }
            if "source_type" not in columns:
                self.connection.execute(
                    "ALTER TABLE sources ADD COLUMN source_type TEXT NOT NULL "
                    "DEFAULT 'local_files' CHECK(source_type IN ('local_files','chat_export'))"
                )
            self.connection.executescript(
                """
                UPDATE sources SET source_type='chat_export'
                WHERE EXISTS (
                    SELECT 1 FROM documents
                    WHERE documents.source_id=sources.source_id
                      AND documents.document_id LIKE 'chat:%'
                );
                PRAGMA user_version = 11;
                """
            )
            self.connection.commit()

    def record_agent_decision(
        self,
        *,
        event_id: str,
        idempotency_key: str | None,
        action: str,
        source_id: str,
        decision: str,
        risk: str,
        reason_code: str,
    ) -> bool:
        """Persist metadata-only policy evidence; never accepts prompts or document content."""
        self.get_source(source_id)
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO agent_action_audit VALUES(?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    idempotency_key,
                    action,
                    source_id,
                    decision,
                    risk,
                    reason_code,
                    utc_now(),
                ),
            )
        return cursor.rowcount == 1

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

    def save_qa_turn(
        self,
        *,
        session_id: str | None,
        source_scope: str,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        insufficient_evidence: bool,
        model: str | None,
        retrieval_ms: float,
        generation_ms: float,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> str:
        """Persist one local answer. Session listings never expose turn content."""
        normalized_question = " ".join(question.split())
        if not normalized_question or len(normalized_question) > 500:
            raise ValueError("Question must contain between 1 and 500 characters")
        if source_scope != "all":
            self.get_source(source_scope)
        if session_id is None:
            session_id = str(uuid.uuid4())
        else:
            try:
                session_id = str(uuid.UUID(session_id))
            except ValueError as exc:
                raise ValueError("Invalid Q&A session identifier") from exc
        now = utc_now()
        title = normalized_question[:80]
        encoded_citations = json.dumps(
            citations,
            ensure_ascii=False,
            sort_keys=True,
            default=lambda value: value.isoformat(),
        )
        with self.connection:
            existing = self.connection.execute(
                "SELECT 1 FROM qa_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    "INSERT INTO qa_sessions VALUES(?,?,?,?)",
                    (session_id, title, now, now),
                )
            self.connection.execute(
                """INSERT INTO qa_turns(
                turn_id,session_id,source_scope,question,answer,citations_json,
                insufficient_evidence,model,retrieval_ms,generation_ms,prompt_tokens,
                completion_tokens,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    session_id,
                    source_scope,
                    normalized_question,
                    answer,
                    encoded_citations,
                    int(insufficient_evidence),
                    model,
                    float(retrieval_ms),
                    float(generation_ms),
                    prompt_tokens,
                    completion_tokens,
                    now,
                ),
            )
            self.connection.execute(
                "UPDATE qa_sessions SET updated_at=? WHERE session_id=?",
                (now, session_id),
            )
        return session_id

    def list_qa_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return metadata-only session summaries for the local history sidebar."""
        bounded_limit = max(1, min(int(limit), 100))
        rows = self.connection.execute(
            """SELECT s.session_id,s.title,s.created_at,s.updated_at,
            COUNT(t.turn_id) AS turn_count
            FROM qa_sessions s LEFT JOIN qa_turns t ON t.session_id=s.session_id
            GROUP BY s.session_id ORDER BY s.updated_at DESC,s.session_id LIMIT ?""",
            (bounded_limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_qa_session(self, session_id: str) -> dict[str, Any]:
        try:
            normalized_id = str(uuid.UUID(session_id))
        except ValueError as exc:
            raise ValueError("Invalid Q&A session identifier") from exc
        session = self.connection.execute(
            "SELECT * FROM qa_sessions WHERE session_id=?", (normalized_id,)
        ).fetchone()
        if session is None:
            raise KeyError("Q&A session not found")
        rows = self.connection.execute(
            "SELECT * FROM qa_turns WHERE session_id=? ORDER BY created_at,turn_id",
            (normalized_id,),
        ).fetchall()
        turns: list[dict[str, Any]] = []
        for row in rows:
            turn = dict(row)
            turn["citations"] = json.loads(str(turn.pop("citations_json")))
            turn["insufficient_evidence"] = bool(turn["insufficient_evidence"])
            turns.append(turn)
        result = dict(session)
        result["turns"] = turns
        return result

    def delete_qa_session(self, session_id: str) -> dict[str, int | str]:
        session = self.get_qa_session(session_id)
        count = len(session["turns"])
        normalized_id = str(session["session_id"])
        with self.connection:
            self.connection.execute(
                "DELETE FROM qa_sessions WHERE session_id=?", (normalized_id,)
            )
        return {"session_id": normalized_id, "turns": count}

    def set_source_schedule(
        self,
        source_id: str,
        *,
        frequency: str,
        enabled: bool,
        pause_on_battery: bool = True,
        auto_lexical: bool = True,
        auto_vector: bool = True,
        next_run_at: str | None = None,
    ) -> dict[str, Any]:
        self.get_source(source_id)
        if frequency not in {"manual", "hourly", "daily"}:
            raise ValueError("Schedule frequency must be manual, hourly, or daily")
        if frequency == "manual":
            enabled = False
            next_run_at = None
        with self.connection:
            self.connection.execute(
                """INSERT INTO source_schedules(
                source_id,frequency,enabled,pause_on_battery,auto_lexical,auto_vector,
                next_run_at,last_started_at,last_finished_at,last_status,last_error)
                VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)
                ON CONFLICT(source_id) DO UPDATE SET
                frequency=excluded.frequency,enabled=excluded.enabled,
                pause_on_battery=excluded.pause_on_battery,
                auto_lexical=excluded.auto_lexical,auto_vector=excluded.auto_vector,
                next_run_at=excluded.next_run_at""",
                (
                    source_id,
                    frequency,
                    int(enabled),
                    int(pause_on_battery),
                    int(auto_lexical),
                    int(auto_vector),
                    next_run_at,
                ),
            )
        return self.get_source_schedule(source_id)

    def get_source_schedule(self, source_id: str) -> dict[str, Any]:
        self.get_source(source_id)
        row = self.connection.execute(
            "SELECT * FROM source_schedules WHERE source_id=?", (source_id,)
        ).fetchone()
        if row is None:
            return {
                "source_id": source_id,
                "frequency": "manual",
                "enabled": False,
                "pause_on_battery": True,
                "auto_lexical": True,
                "auto_vector": True,
                "next_run_at": None,
                "last_started_at": None,
                "last_finished_at": None,
                "last_status": None,
                "last_error": None,
            }
        result = dict(row)
        for key in ("enabled", "pause_on_battery", "auto_lexical", "auto_vector"):
            result[key] = bool(result[key])
        return result

    def list_source_schedules(self) -> list[dict[str, Any]]:
        return [self.get_source_schedule(source.source_id) for source in self.list_sources()]

    def due_source_schedules(self, now: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT * FROM source_schedules
            WHERE enabled=1 AND frequency!='manual' AND next_run_at<=?
            ORDER BY next_run_at,source_id""",
            (now,),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_schedule_result(
        self,
        source_id: str,
        *,
        started_at: str,
        finished_at: str,
        status: str,
        next_run_at: str,
        error: str | None = None,
    ) -> None:
        if status not in {"SUCCEEDED", "FAILED", "SKIPPED"}:
            raise ValueError("Invalid schedule status")
        safe_error = error.replace("\n", " ")[:500] if error else None
        with self.connection:
            self.connection.execute(
                """UPDATE source_schedules SET last_started_at=?,last_finished_at=?,
                last_status=?,last_error=?,next_run_at=? WHERE source_id=?""",
                (started_at, finished_at, status, safe_error, next_run_at, source_id),
            )

    def register_source(
        self,
        root: Path,
        max_file_size: int,
        max_depth: int,
        extensions: frozenset[str],
        source_type: str = "local_files",
    ) -> RegisteredSource:
        if source_type not in {"local_files", "chat_export"}:
            raise ValueError("Unsupported source type")
        root_text = str(root)
        existing = self.connection.execute(
            "SELECT * FROM sources WHERE root_path=?", (root_text,)
        ).fetchone()
        if existing is None:
            source_id = str(uuid.uuid4())
            with self.connection:
                self.connection.execute(
                    "INSERT INTO sources(source_id,root_path,allowed_extensions,max_file_size,"
                    "max_depth,created_at,last_successful_run_id,last_successful_at,source_type) "
                    "VALUES(?,?,?,?,?,?,NULL,NULL,?)",
                    (
                        source_id,
                        root_text,
                        json.dumps(sorted(extensions)),
                        max_file_size,
                        max_depth,
                        utc_now(),
                        source_type,
                    ),
                )
        else:
            source_id = existing["source_id"]
            existing_extensions = frozenset(json.loads(existing["allowed_extensions"]))
            merged_extensions = existing_extensions | extensions
            if merged_extensions != existing_extensions:
                with self.connection:
                    self.connection.execute(
                        "UPDATE sources SET allowed_extensions=? WHERE source_id=?",
                        (json.dumps(sorted(merged_extensions)), source_id),
                    )
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
            source_type=str(row["source_type"]),
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
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO sync_runs(run_id,source_id,status,started_at) "
                    "VALUES(?,?,'RUNNING',?)",
                    (run_id, source_id, utc_now()),
                )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("A synchronization is already running for this source") from exc
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

    def apply_scan(
        self,
        run_id: str,
        source_id: str,
        files: list[ScannedFile],
        *,
        retained_object_ids: set[str] | None = None,
        retained_path_prefixes: set[str] | None = None,
    ) -> dict[str, int]:
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
            current_ids: set[str] = set(retained_object_ids or ())
            prefixes = tuple(f"{path.rstrip('/')}/" for path in retained_path_prefixes or ())
            if prefixes:
                current_ids.update(
                    object_id
                    for object_id, row in previous.items()
                    if str(row["relative_path"]).startswith(prefixes)
                )
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
