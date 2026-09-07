"""Deterministic, budgeted context selection for grounded answers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from mini_gl.domain.models import Citation
from mini_gl.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class ContextBundle:
    text: str
    citations: tuple[Citation, ...]


class ContextBuilder:
    def __init__(self, store: SQLiteStore, *, max_chars: int = 6_000, max_chunks: int = 6) -> None:
        if max_chars < 200 or not 1 <= max_chunks <= 20:
            raise ValueError("Invalid context budget")
        self.store = store
        self.max_chars = max_chars
        self.max_chunks = max_chunks

    def build(self, source_id: str, ranked: list[dict[str, object]]) -> ContextBundle:
        sections: list[str] = []
        citations: list[Citation] = []
        seen: set[str] = set()
        remaining = self.max_chars
        for result in ranked:
            if len(sections) >= self.max_chunks or remaining <= 0:
                break
            row = self.store.connection.execute(
                "SELECT chunk_id,document_id,source_uri,title,content FROM lexical_chunks "
                "WHERE source_id=? AND chunk_id=?",
                (source_id, str(result["chunk_id"])),
            ).fetchone()
            if row is None:
                continue
            digest = hashlib.sha256(str(row["content"]).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            label = len(citations) + 1
            header = f"[来源 {label}] {row['title']}\n"
            available = remaining - len(header)
            if available <= 0:
                break
            content = str(row["content"])[:available]
            sections.append(header + content)
            remaining -= len(header) + len(content)
            citations.append(
                Citation(
                    document_id=str(row["document_id"]),
                    chunk_id=str(row["chunk_id"]),
                    source_uri=str(row["source_uri"]),
                    title=str(row["title"]),
                    start_offset=0,
                    end_offset=len(content),
                )
            )
        return ContextBundle("\n\n".join(sections), tuple(citations))
