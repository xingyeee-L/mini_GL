"""Deterministic, budgeted context selection for grounded answers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from mini_gl.domain.models import Citation
from mini_gl.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class ContextBundle:
    text: str
    citations: tuple[Citation, ...]
    evidence: tuple[str, ...]
    estimated_tokens: int


class ConservativeTokenCounter:
    """Overestimate mixed Chinese/Latin tokens without loading remote tokenizer code."""

    _latin = re.compile(r"[A-Za-z0-9_]+|[^A-Za-z0-9_\s]")

    def count(self, text: str) -> int:
        cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
        without_cjk = "".join(" " if "\u3400" <= char <= "\u9fff" else char for char in text)
        latin = sum(max(1, (len(token) + 3) // 4) for token in self._latin.findall(without_cjk))
        return cjk + latin


class ContextBuilder:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        max_tokens: int = 3_000,
        max_chunks: int = 6,
    ) -> None:
        if max_tokens < 100 or not 1 <= max_chunks <= 20:
            raise ValueError("Invalid context budget")
        self.store = store
        self.max_tokens = max_tokens
        self.max_chunks = max_chunks
        self.counter = ConservativeTokenCounter()

    def build(self, source_id: str, ranked: list[dict[str, object]]) -> ContextBundle:
        return self.build_many((source_id,), ranked)

    def build_many(
        self, source_ids: tuple[str, ...], ranked: list[dict[str, object]]
    ) -> ContextBundle:
        """Build one bounded context from results already authorized per source."""
        allowed_sources = frozenset(source_ids)
        sections: list[str] = []
        citations: list[Citation] = []
        evidence: list[str] = []
        seen: set[str] = set()
        used_tokens = 0
        for result in ranked:
            if len(sections) >= self.max_chunks or used_tokens >= self.max_tokens:
                break
            result_source = str(result.get("source_id", ""))
            if result_source not in allowed_sources:
                continue
            row = self.store.connection.execute(
                "SELECT chunk_id,document_id,source_id,source_uri,title,content,"
                "section_path,start_offset,end_offset "
                "FROM lexical_chunks "
                "WHERE source_id=? AND chunk_id=?",
                (result_source, str(result["chunk_id"])),
            ).fetchone()
            if row is None:
                continue
            digest = hashlib.sha256(str(row["content"]).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            label = len(citations) + 1
            section = f" · {row['section_path']}" if row["section_path"] else ""
            header = f"[来源 {label}] {row['title']}{section}\n"
            header_tokens = self.counter.count(header)
            available_tokens = self.max_tokens - used_tokens - header_tokens
            if available_tokens <= 0:
                break
            content = _fit_tokens(str(row["content"]), available_tokens, self.counter)
            if not content:
                break
            sections.append(header + content)
            evidence.append(content)
            used_tokens += header_tokens + self.counter.count(content)
            citations.append(
                Citation(
                    document_id=str(row["document_id"]),
                    chunk_id=str(row["chunk_id"]),
                    source_uri=str(row["source_uri"]),
                    title=str(row["title"]),
                    source_id=str(row["source_id"]),
                    section_path=str(row["section_path"]) or None,
                    start_offset=int(row["start_offset"]),
                    end_offset=min(
                        int(row["end_offset"]), int(row["start_offset"]) + len(content)
                    ),
                )
            )
        return ContextBundle(
            "\n\n".join(sections), tuple(citations), tuple(evidence), used_tokens
        )


def _fit_tokens(text: str, budget: int, counter: ConservativeTokenCounter) -> str:
    if counter.count(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if counter.count(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]
