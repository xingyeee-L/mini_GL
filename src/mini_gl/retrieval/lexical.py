"""Deterministic local BM25 retrieval with Chinese bigram tokenization."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_gl.storage.sqlite import SQLiteStore

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z0-9_]+")
_TECHNICAL_SEPARATOR = re.compile(r"(?<=[a-z0-9])[-_.](?=[a-z0-9])")
_QUESTION_NOISE = (
    "会不会",
    "是不是",
    "应该怎么",
    "如何",
    "怎么",
    "哪些",
    "什么",
    "是否",
    "一个",
    "我的",
)


def tokenize(text: str) -> list[str]:
    """Create lowercase words plus Chinese unigrams and bigrams."""
    normalized = _TECHNICAL_SEPARATOR.sub("", text.casefold())
    for phrase in _QUESTION_NOISE:
        normalized = normalized.replace(phrase, " ")
    tokens = _WORD.findall(normalized)
    for run in _CJK.findall(normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


@dataclass(frozen=True, slots=True)
class StructuredChunk:
    content: str
    section_path: str
    start_offset: int
    end_offset: int


def split_structured_chunks(
    content: str, *, file_type: str = "", limit: int = 900
) -> list[StructuredChunk]:
    """Split paragraphs while preserving Markdown heading ancestry and offsets."""
    heading_stack: list[str] = []
    chunks: list[StructuredChunk] = []
    scan_content = content.rstrip()
    blocks = list(
        re.finditer(
            r"\S(?:.*?\S)?(?=\r?\n[ \t]*\r?\n|\Z)", scan_content, re.DOTALL
        )
    )
    for block in blocks:
        raw = block.group(0)
        heading = (
            re.fullmatch(r"\s*(#{1,6})\s+(.+?)\s*", raw)
            if file_type in {".md", ".markdown"}
            else None
        )
        if heading:
            level = len(heading.group(1))
            heading_stack[level - 1 :] = [heading.group(2).strip()]
            continue
        section_path = " › ".join(heading_stack)
        stripped = raw.strip()
        leading = len(raw) - len(raw.lstrip())
        absolute_start = block.start() + leading
        for offset in range(0, len(stripped), limit):
            part = stripped[offset : offset + limit]
            chunks.append(
                StructuredChunk(
                    part,
                    section_path,
                    absolute_start + offset,
                    absolute_start + offset + len(part),
                )
            )
    return chunks


def split_chunks(content: str, limit: int = 900) -> list[str]:
    """Compatibility wrapper returning only chunk text."""
    return [chunk.content for chunk in split_structured_chunks(content, limit=limit)]


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: str
    document_id: str
    source_id: str
    title: str
    source_uri: str
    file_type: str
    updated_at: str | None
    section_path: str
    start_offset: int
    end_offset: int
    snippet: str
    score: float


class LexicalSearchService:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def rebuild(self, source_id: str | None = None) -> dict[str, int]:
        rows, document_count = self._build_rows(source_id)
        with self.store.connection:
            if source_id is None:
                self.store.connection.execute("DELETE FROM lexical_chunks")
            else:
                self.store.connection.execute(
                    "DELETE FROM lexical_chunks WHERE source_id=?", (source_id,)
                )
            self.store.connection.executemany(
                """INSERT INTO lexical_chunks(
                chunk_id,document_id,source_id,ordinal,source_uri,title,file_type,
                updated_at,content,terms_json,token_count,section_path,start_offset,end_offset
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return {"documents": document_count, "chunks": len(rows)}

    def sync(self, source_id: str) -> dict[str, int]:
        """Update one source while retaining unchanged chunk IDs and their vectors."""
        rows, document_count = self._build_rows(source_id)
        current = {str(row[0]): row for row in rows}
        existing = {
            str(row["chunk_id"]): row
            for row in self.store.connection.execute(
                "SELECT * FROM lexical_chunks WHERE source_id=?", (source_id,)
            )
        }
        deleted = existing.keys() - current.keys()
        created = current.keys() - existing.keys()
        unchanged = current.keys() & existing.keys()
        with self.store.connection:
            self.store.connection.executemany(
                "DELETE FROM lexical_chunks WHERE chunk_id=?", ((item,) for item in deleted)
            )
            self.store.connection.executemany(
                """INSERT INTO lexical_chunks(
                chunk_id,document_id,source_id,ordinal,source_uri,title,file_type,
                updated_at,content,terms_json,token_count,section_path,start_offset,end_offset
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                source_uri=excluded.source_uri,title=excluded.title,file_type=excluded.file_type,
                updated_at=excluded.updated_at,content=excluded.content,
                terms_json=excluded.terms_json,token_count=excluded.token_count,
                section_path=excluded.section_path,start_offset=excluded.start_offset,
                end_offset=excluded.end_offset""",
                current.values(),
            )
        return {
            "documents": document_count,
            "created": len(created),
            "unchanged": len(unchanged),
            "deleted": len(deleted),
            "chunks": len(rows),
        }

    def _build_rows(self, source_id: str | None) -> tuple[list[tuple[object, ...]], int]:
        if source_id is None:
            documents = self.store.connection.execute(
                "SELECT document_id,source_id,source_uri,title,content,updated_at FROM documents"
            ).fetchall()
        else:
            documents = self.store.connection.execute(
                "SELECT document_id,source_id,source_uri,title,content,updated_at "
                "FROM documents WHERE source_id=?",
                (source_id,),
            ).fetchall()
        rows: list[tuple[object, ...]] = []
        for document in documents:
            file_type = Path(document["source_uri"]).suffix.lower()
            for ordinal, chunk in enumerate(
                split_structured_chunks(document["content"], file_type=file_type)
            ):
                content = chunk.content
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                identity = f"{document['document_id']}\0{ordinal}\0{content_hash}"
                chunk_id = hashlib.sha256(identity.encode()).hexdigest()
                title_terms = tokenize(document["title"])
                section_terms = tokenize(chunk.section_path)
                terms = [
                    *title_terms,
                    *title_terms,
                    *section_terms,
                    *section_terms,
                    *tokenize(content),
                ]
                rows.append(
                    (
                        chunk_id,
                        document["document_id"],
                        document["source_id"],
                        ordinal,
                        document["source_uri"],
                        document["title"],
                        file_type,
                        document["updated_at"],
                        content,
                        json.dumps(Counter(terms), ensure_ascii=False, sort_keys=True),
                        len(terms),
                        chunk.section_path,
                        chunk.start_offset,
                        chunk.end_offset,
                    )
                )
        return rows, len(documents)

    def search(
        self,
        query: str,
        *,
        source_id: str | None = None,
        file_type: str | None = None,
        updated_after: str | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        started = time.perf_counter()
        query_terms = Counter(tokenize(query))
        if not query_terms:
            return {"query": query, "elapsed_ms": 0.0, "results": []}
        normalized_type = file_type.lower() if file_type else None
        rows = self.store.connection.execute(
            "SELECT * FROM lexical_chunks WHERE (? IS NULL OR source_id=?) "
            "AND (? IS NULL OR file_type=?) AND (? IS NULL OR updated_at>=?)",
            (
                source_id,
                source_id,
                normalized_type,
                normalized_type,
                updated_after,
                updated_after,
            ),
        ).fetchall()
        if not rows:
            return {"query": query, "elapsed_ms": _elapsed(started), "results": []}
        frequencies = [json.loads(row["terms_json"]) for row in rows]
        document_frequency = {
            term: sum(1 for terms in frequencies if term in terms) for term in query_terms
        }
        average_length = sum(row["token_count"] for row in rows) / len(rows)
        ranked: list[SearchResult] = []
        for row, frequencies_for_row in zip(rows, frequencies, strict=True):
            if _weighted_coverage(
                query_terms, frequencies_for_row, document_frequency, len(rows)
            ) < 0.08:
                continue
            score = _bm25(
                query_terms,
                frequencies_for_row,
                document_frequency,
                len(rows),
                row["token_count"],
                average_length,
            )
            if score <= 0:
                continue
            ranked.append(
                SearchResult(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    source_id=row["source_id"],
                    title=row["title"],
                    source_uri=row["source_uri"],
                    file_type=row["file_type"],
                    updated_at=row["updated_at"],
                    section_path=row["section_path"],
                    start_offset=row["start_offset"],
                    end_offset=row["end_offset"],
                    snippet=_snippet(row["content"], query),
                    score=round(score, 6),
                )
            )
        ranked.sort(key=lambda result: (-result.score, result.chunk_id))
        return {
            "query": query,
            "elapsed_ms": _elapsed(started),
            "results": [asdict(result) for result in ranked[: max(1, min(limit, 50))]],
        }


def _bm25(
    query: Counter[str],
    document: dict[str, int],
    document_frequency: dict[str, int],
    count: int,
    length: int,
    average_length: float,
) -> float:
    score = 0.0
    for term, query_frequency in query.items():
        frequency = document.get(term, 0)
        if not frequency:
            continue
        numerator = count - document_frequency[term] + 0.5
        inverse_frequency = math.log(1 + numerator / (document_frequency[term] + 0.5))
        denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / average_length)
        score += inverse_frequency * frequency * 2.2 / denominator * query_frequency
    return score


def _weighted_coverage(
    query: Counter[str],
    document: dict[str, int],
    document_frequency: dict[str, int],
    count: int,
) -> float:
    # Whole unsegmented Chinese runs are brittle for paraphrases; coverage should
    # be decided by stable bigrams while exact long runs can still boost BM25.
    informative = [
        term for term in query if term.isascii() or len(term) == 2
    ]
    if not informative:
        informative = list(query)
    weights = {
        term: 1 + math.log((count + 1) / (document_frequency.get(term, 0) + 1))
        for term in informative
    }
    total = sum(weights.values())
    return sum(weight for term, weight in weights.items() if term in document) / total


def _snippet(content: str, query: str, width: int = 180) -> str:
    lowered = content.casefold()
    positions = [lowered.find(term) for term in tokenize(query) if len(term) > 1]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - width // 3)
    end = min(len(content), start + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(content) else ""
    return prefix + content[start:end].replace("\n", " ") + suffix


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
