"""Strict parser for the versioned, provider-neutral chat export format."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mini_gl.domain.models import ChatMessage
from mini_gl.parsers.text import TextParseError

MAX_CHAT_EXPORT_SIZE = 10 * 1024 * 1024
MESSAGE_TYPES = frozenset({"text", "image", "file", "audio", "video", "system"})


@dataclass(frozen=True, slots=True)
class ChatExport:
    platform: str
    conversation_id: str
    title: str
    participants: tuple[str, ...]
    messages: tuple[ChatMessage, ...]


def parse_chat_export(path: Path) -> ChatExport:
    value = read_stable_json(path)
    return _validate(value, path)


def read_stable_json(path: Path) -> Any:
    before = path.stat()
    if before.st_size > MAX_CHAT_EXPORT_SIZE:
        raise TextParseError("Chat export exceeds the 10 MiB safety limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TextParseError("Unable to read chat export") from exc
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(raw) != before.st_size:
        raise TextParseError("Chat export changed while it was being read")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TextParseError("Chat export must be valid UTF-8 JSON") from exc


def _validate(value: Any, path: Path) -> ChatExport:
    root = _object(value, "root")
    if root.get("schema_version") != "1.0":
        raise ValueError("Unsupported chat schema_version; expected 1.0")
    platform = _text(root, "platform", 80)
    conversation = _object(root.get("conversation"), "conversation")
    conversation_id = _text(conversation, "id", 200)
    title = _text(conversation, "title", 300)
    participants = _string_list(conversation.get("participants"), "participants", 500)
    raw_messages = root.get("messages")
    if not isinstance(raw_messages, list) or len(raw_messages) > 100_000:
        raise ValueError("messages must be an array with at most 100000 items")
    seen: set[str] = set()
    messages: list[ChatMessage] = []
    for index, raw in enumerate(raw_messages):
        item = _object(raw, f"messages[{index}]")
        message_id = _text(item, "id", 200)
        if message_id in seen:
            raise ValueError(f"Duplicate message id: {message_id}")
        seen.add(message_id)
        sent_at = _timestamp(_text(item, "sent_at", 80))
        message_type = _text(item, "message_type", 30)
        if message_type not in MESSAGE_TYPES:
            raise ValueError(f"Unsupported message_type: {message_type}")
        text = item.get("text")
        if text is not None and (not isinstance(text, str) or len(text) > 1_000_000):
            raise ValueError("message text must be a string no longer than 1000000 characters")
        attachments = _string_list(item.get("attachment_refs", []), "attachment_refs", 1000)
        withdrawn = item.get("withdrawn", False)
        if not isinstance(withdrawn, bool):
            raise ValueError("withdrawn must be boolean")
        messages.append(
            ChatMessage(
                id=message_id,
                platform=platform,
                conversation_id=conversation_id,
                sender_id=_text(item, "sender_id", 200),
                sender_name=_optional_text(item.get("sender_name"), 300),
                sent_at=sent_at,
                message_type=message_type,
                text=None if withdrawn else text,
                attachment_refs=attachments,
                reply_to=_optional_text(item.get("reply_to"), 200),
                source_uri=str(path),
                metadata={"withdrawn": withdrawn},
            )
        )
    messages.sort(key=lambda message: (message.sent_at, message.id))
    if any(message.reply_to and message.reply_to not in seen for message in messages):
        raise ValueError("reply_to must reference a message in the same export")
    return ChatExport(platform, conversation_id, title, participants, tuple(messages))


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: dict[str, Any], key: str, limit: int) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or len(result) > limit:
        raise ValueError(f"{key} must be a non-empty string no longer than {limit} characters")
    return result.strip()


def _optional_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("optional text field has an invalid value")
    return value


def _string_list(value: Any, name: str, limit: int) -> tuple[str, ...]:
    valid = isinstance(value, list) and len(value) <= limit
    if not valid or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{name} must be a string array with at most {limit} items")
    return tuple(value)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid sent_at timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("sent_at timestamps must include a timezone")
    return parsed
