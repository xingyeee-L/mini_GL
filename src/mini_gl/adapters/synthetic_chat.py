"""Synthetic QQ/WeChat adapters; these do not access installed chat clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mini_gl.parsers.chat_json import MAX_CHAT_EXPORT_SIZE
from mini_gl.security.paths import PathPolicy


def convert_export(kind: str, source: Path, destination: Path) -> dict[str, object]:
    if kind not in {"qq", "wechat"}:
        raise ValueError("Adapter must be qq or wechat")
    canonical = PathPolicy(
        (source.parent,), frozenset({".json"}), MAX_CHAT_EXPORT_SIZE, 0
    ).authorize(source)
    try:
        raw = json.loads(canonical.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Adapter input must be valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("Adapter input root must be an object")
    neutral = _convert_qq(raw) if kind == "qq" else _convert_wechat(raw)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destination already exists; refusing to overwrite it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(neutral, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"destination": str(destination.resolve()), "messages": len(neutral["messages"])}


def _convert_qq(root: dict[str, Any]) -> dict[str, Any]:
    chat = _dict(root.get("chat"), "chat")
    messages = root.get("records")
    if not isinstance(messages, list):
        raise ValueError("QQ records must be an array")
    return {
        "schema_version": "1.0",
        "platform": "qq-export",
        "conversation": {
            "id": _required(chat, "uin"),
            "title": _required(chat, "name"),
            "participants": _strings(chat.get("members"), "members"),
        },
        "messages": [
            {
                "id": _required(_dict(item, "record"), "msg_id"),
                "sender_id": _required(item, "sender_uin"),
                "sender_name": item.get("nickname"),
                "sent_at": _required(item, "time"),
                "message_type": item.get("type", "text"),
                "text": item.get("content"),
                "reply_to": item.get("reply_msg_id"),
                "attachment_refs": item.get("attachments", []),
                "withdrawn": item.get("recalled", False),
            }
            for item in messages
        ],
    }


def _convert_wechat(root: dict[str, Any]) -> dict[str, Any]:
    session = _dict(root.get("session"), "session")
    messages = root.get("messages")
    if not isinstance(messages, list):
        raise ValueError("WeChat messages must be an array")
    return {
        "schema_version": "1.0",
        "platform": "wechat-export",
        "conversation": {
            "id": _required(session, "talker_id"),
            "title": _required(session, "display_name"),
            "participants": _strings(session.get("member_ids"), "member_ids"),
        },
        "messages": [
            {
                "id": _required(_dict(item, "message"), "local_id"),
                "sender_id": _required(item, "from_id"),
                "sender_name": item.get("from_name"),
                "sent_at": _required(item, "timestamp"),
                "message_type": item.get("kind", "text"),
                "text": item.get("body"),
                "reply_to": item.get("quote_id"),
                "attachment_refs": item.get("media_refs", []),
                "withdrawn": item.get("revoked", False),
            }
            for item in messages
        ],
    }


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _required(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string array")
    return value
