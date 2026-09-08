"""Bounded synthetic reliability benchmarks; never reads user source data."""

from __future__ import annotations

import hashlib
import tempfile
import time
import tracemalloc
from pathlib import Path

from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.storage.sqlite import SQLiteStore

MAX_BENCHMARK_FILES = 5_000
MAX_BENCHMARK_FILE_SIZE = 10 * 1024 * 1024
MAX_BENCHMARK_TOTAL_SIZE = 64 * 1024 * 1024


def run_ingestion_benchmark(file_count: int = 500, file_size: int = 1024) -> dict[str, object]:
    """Measure a synthetic ingestion/indexing run within explicit resource bounds."""
    if not 1 <= file_count <= MAX_BENCHMARK_FILES:
        raise ValueError(f"File count must be between 1 and {MAX_BENCHMARK_FILES}")
    if not 1 <= file_size <= MAX_BENCHMARK_FILE_SIZE:
        raise ValueError(f"File size must be between 1 and {MAX_BENCHMARK_FILE_SIZE} bytes")
    if file_count * file_size > MAX_BENCHMARK_TOTAL_SIZE:
        raise ValueError(f"Total generated size must not exceed {MAX_BENCHMARK_TOTAL_SIZE} bytes")

    with tempfile.TemporaryDirectory(prefix="mini-gl-benchmark-") as temp_dir:
        base = Path(temp_dir)
        root = base / "synthetic-source"
        root.mkdir()
        seed = "synthetic reliability benchmark content 可靠性基准\n".encode()
        payload = (seed * (file_size // len(seed) + 1))[:file_size]
        for number in range(file_count):
            (root / f"document-{number:05d}.txt").write_bytes(payload)
        before = _tree_digest(root)

        database = base / "benchmark.sqlite3"
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        tracemalloc.start()
        try:
            with SQLiteStore(database) as store:
                ingestion = IngestionService(store)
                source = ingestion.register(root)
                sync = ingestion.sync(source.source_id)
                index = LexicalSearchService(store).rebuild(source.source_id)
                status = store.status(source.source_id)[0]
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        wall_ms = round((time.perf_counter() - wall_started) * 1000, 3)
        cpu_ms = round((time.process_time() - cpu_started) * 1000, 3)
        after = _tree_digest(root)
        return {
            "fixture": "generated-synthetic-only",
            "files": file_count,
            "bytes_per_file": file_size,
            "created": sync["created"],
            "documents": status["file_count"],
            "lexical_chunks": index["chunks"],
            "wall_ms": wall_ms,
            "cpu_ms": cpu_ms,
            "python_peak_mib": round(peak_bytes / (1024 * 1024), 3),
            "database_mib": round(database.stat().st_size / (1024 * 1024), 3),
            "source_unchanged": before == after,
        }


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
