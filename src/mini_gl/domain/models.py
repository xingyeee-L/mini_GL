"""Canonical, provider-independent data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: str
    source_type: str
    source_uri: str
    title: str
    content: str
    content_hash: str
    access_scope: str = "owner-only"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    participants: tuple[str, ...] = ()
    conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: str
    platform: str
    conversation_id: str
    sender_id: str
    sent_at: datetime
    message_type: str
    source_uri: str
    access_scope: str = "owner-only"
    sender_name: str | None = None
    text: str | None = None
    attachment_refs: tuple[str, ...] = ()
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchChunk:
    id: str
    document_id: str
    text: str
    chunk_index: int
    content_hash: str
    access_scope: str = "owner-only"
    start_offset: int | None = None
    end_offset: int | None = None
    timestamp_start: datetime | None = None
    timestamp_end: datetime | None = None
    participants: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Citation:
    document_id: str
    chunk_id: str
    source_uri: str
    title: str
    source_id: str | None = None
    section_path: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    timestamp_start: datetime | None = None
    timestamp_end: datetime | None = None


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    citations: tuple[Citation, ...]
    insufficient_evidence: bool
    model: str | None
    retrieval_ms: float
    generation_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw_model_answer: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)
