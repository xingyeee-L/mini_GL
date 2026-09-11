"""Read-only import of neutral chat JSON into canonical searchable documents."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from mini_gl.connectors.local_files import ScannedFile, object_id_for
from mini_gl.domain.models import ChatMessage, SourceDocument
from mini_gl.parsers.chat_json import MAX_CHAT_EXPORT_SIZE, ChatExport, parse_chat_export
from mini_gl.security.paths import PathPolicy
from mini_gl.storage.sqlite import SQLiteStore

WINDOW_GAP = timedelta(minutes=30)
MAX_MESSAGES_PER_WINDOW = 100


class ChatImportService:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def import_file(self, path: Path, *, authorized: bool = False) -> dict[str, object]:
        if not authorized:
            raise PermissionError("Confirm that you are authorized to use this chat export")
        canonical = PathPolicy(
            (path.parent,), frozenset({".json"}), MAX_CHAT_EXPORT_SIZE, 0
        ).authorize(path)
        export = parse_chat_export(canonical)
        source = self.store.register_source(
            canonical, MAX_CHAT_EXPORT_SIZE, 0, frozenset({".json"}), "chat_export"
        )
        run_id = self.store.start_run(source.source_id)
        try:
            scanned = self._documents(source.source_id, canonical, export)
            counts = self.store.apply_scan(run_id, source.source_id, scanned)
        except Exception as exc:
            self.store.fail_run(run_id, exc)
            raise
        return {"source_id": source.source_id, "documents": len(scanned), **counts}

    def _documents(self, source_id: str, path: Path, export: ChatExport) -> list[ScannedFile]:
        stat = path.stat()
        windows = split_conversation(export.messages)
        result: list[ScannedFile] = []
        for index, messages in enumerate(windows):
            relative = f"{export.conversation_id}/window-{index:05d}.chat"
            object_id = object_id_for(source_id, relative)
            content = render_messages(messages)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            participants = tuple(dict.fromkeys(m.sender_id for m in messages))
            document = SourceDocument(
                id=f"chat:{source_id}:{object_id}",
                source_type="chat_export",
                source_uri=str(path),
                title=f"{export.title} · {messages[0].sent_at:%Y-%m-%d %H:%M}",
                content=content,
                content_hash=digest,
                created_at=messages[0].sent_at,
                updated_at=messages[-1].sent_at,
                participants=participants,
                conversation_id=export.conversation_id,
                metadata={
                    "schema_version": "1.0",
                    "platform": export.platform,
                    "conversation_id": export.conversation_id,
                    "participants": participants,
                    "message_ids": [message.id for message in messages],
                    "timestamp_start": messages[0].sent_at.isoformat(),
                    "timestamp_end": messages[-1].sent_at.isoformat(),
                    "source_filename": path.name,
                },
            )
            result.append(
                ScannedFile(object_id, relative, document, stat.st_size, stat.st_mtime_ns)
            )
        return result


def split_conversation(messages: tuple[ChatMessage, ...]) -> list[tuple[ChatMessage, ...]]:
    windows: list[list[ChatMessage]] = []
    for message in messages:
        new_window = (
            not windows
            or len(windows[-1]) >= MAX_MESSAGES_PER_WINDOW
            or message.sent_at - windows[-1][-1].sent_at > WINDOW_GAP
        )
        if new_window:
            windows.append([])
        windows[-1].append(message)
    return [tuple(window) for window in windows]


def render_messages(messages: tuple[ChatMessage, ...]) -> str:
    lines: list[str] = []
    for message in messages:
        sender = message.sender_name or message.sender_id
        body = message.text if message.text is not None else "[已撤回或无文本内容]"
        attachment = (
            ""
            if not message.attachment_refs
            else f" [附件引用: {', '.join(message.attachment_refs)}]"
        )
        reply = "" if message.reply_to is None else f" [回复: {message.reply_to}]"
        lines.append(f"[{message.sent_at.isoformat()}] {sender}: {body}{attachment}{reply}")
    return "\n".join(lines)
