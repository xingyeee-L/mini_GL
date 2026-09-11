"""Local vector indexing and cosine retrieval."""

from __future__ import annotations

import math
from array import array
from dataclasses import asdict, dataclass

from mini_gl.indexing.embeddings import EmbeddingProvider
from mini_gl.storage.sqlite import SQLiteStore


@dataclass(frozen=True, slots=True)
class VectorResult:
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


class VectorSearchService:
    def __init__(self, store: SQLiteStore, provider: EmbeddingProvider) -> None:
        self.store = store
        self.provider = provider

    def rebuild(self, source_id: str | None = None, batch_size: int = 32) -> dict[str, int]:
        if source_id is None:
            rows = self.store.connection.execute(
                "SELECT chunk_id,source_id,title,content FROM lexical_chunks ORDER BY chunk_id"
            ).fetchall()
        else:
            rows = self.store.connection.execute(
                "SELECT chunk_id,source_id,title,content FROM lexical_chunks "
                "WHERE source_id=? ORDER BY chunk_id",
                (source_id,),
            ).fetchall()
        values: list[tuple[object, ...]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = self.provider.embed_documents(
                [f"{row['title']} {row['content']}" for row in batch]
            )
            for row, vector in zip(batch, vectors, strict=True):
                if len(vector) != self.provider.dimension:
                    raise ValueError("Embedding provider returned an invalid dimension")
                values.append(
                    (
                        row["chunk_id"],
                        row["source_id"],
                        self.provider.name,
                        self.provider.dimension,
                        array("f", vector).tobytes(),
                    )
                )
        with self.store.connection:
            if source_id is None:
                self.store.connection.execute(
                    "DELETE FROM vector_chunks WHERE provider=?", (self.provider.name,)
                )
            else:
                self.store.connection.execute(
                    "DELETE FROM vector_chunks WHERE provider=? AND source_id=?",
                    (self.provider.name, source_id),
                )
            self.store.connection.executemany(
                "INSERT INTO vector_chunks VALUES(?,?,?,?,?)", values
            )
        return {"chunks": len(values), "dimension": self.provider.dimension}

    def sync(self, source_id: str, batch_size: int = 32) -> dict[str, int]:
        """Embed only lexical chunks missing for this provider and source."""
        rows = self.store.connection.execute(
            "SELECT l.chunk_id,l.source_id,l.title,l.content FROM lexical_chunks l "
            "LEFT JOIN vector_chunks v ON v.chunk_id=l.chunk_id AND v.provider=? "
            "WHERE l.source_id=? AND v.chunk_id IS NULL ORDER BY l.chunk_id",
            (self.provider.name, source_id),
        ).fetchall()
        values: list[tuple[object, ...]] = []
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vectors = self.provider.embed_documents(
                [f"{row['title']} {row['content']}" for row in batch]
            )
            for row, vector in zip(batch, vectors, strict=True):
                if len(vector) != self.provider.dimension:
                    raise ValueError("Embedding provider returned an invalid dimension")
                values.append(
                    (
                        row["chunk_id"],
                        row["source_id"],
                        self.provider.name,
                        self.provider.dimension,
                        array("f", vector).tobytes(),
                    )
                )
        with self.store.connection:
            self.store.connection.executemany(
                "INSERT INTO vector_chunks VALUES(?,?,?,?,?)", values
            )
        total = self.store.connection.execute(
            "SELECT COUNT(*) FROM vector_chunks WHERE source_id=? AND provider=?",
            (source_id, self.provider.name),
        ).fetchone()[0]
        return {
            "embedded": len(values),
            "reused": total - len(values),
            "chunks": total,
            "dimension": self.provider.dimension,
        }

    def search(
        self,
        query: str,
        source_id: str,
        limit: int = 10,
        *,
        file_type: str | None = None,
        updated_after: str | None = None,
    ) -> list[dict[str, object]]:
        query_vector = self.provider.embed_query(query)
        normalized_type = file_type.lower() if file_type else None
        rows = self.store.connection.execute(
            "SELECT l.*,v.vector FROM vector_chunks v JOIN lexical_chunks l "
            "ON l.chunk_id=v.chunk_id WHERE v.provider=? AND v.source_id=? "
            "AND (? IS NULL OR l.file_type=?) AND (? IS NULL OR l.updated_at>=?)",
            (
                self.provider.name,
                source_id,
                normalized_type,
                normalized_type,
                updated_after,
                updated_after,
            ),
        ).fetchall()
        results: list[VectorResult] = []
        for row in rows:
            vector = array("f")
            vector.frombytes(row["vector"])
            score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
            if math.isfinite(score) and score > 0:
                results.append(
                    VectorResult(
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
                        snippet=row["content"][:180].replace("\n", " "),
                        score=round(score, 6),
                    )
                )
        results.sort(key=lambda result: (-result.score, result.chunk_id))
        return [asdict(result) for result in results[: max(1, min(limit, 50))]]
