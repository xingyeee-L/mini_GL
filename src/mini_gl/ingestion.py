"""Application service for source registration and synchronization."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mini_gl.connectors.local_files import LocalFileConnector
from mini_gl.security.paths import DEFAULT_MAX_DEPTH, DEFAULT_MAX_FILE_SIZE, PathPolicy
from mini_gl.storage.sqlite import RegisteredSource, SQLiteStore

DEFAULT_EXTENSIONS = frozenset({".txt", ".md"})


class IngestionService:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def register(
        self,
        root: Path,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> RegisteredSource:
        policy = PathPolicy((root,), DEFAULT_EXTENSIONS, max_file_size, max_depth)
        canonical = policy.authorize_root(root)
        return self.store.register_source(canonical, max_file_size, max_depth, DEFAULT_EXTENSIONS)

    def sync(
        self, source_id: str, *, after_scan: Callable[[], None] | None = None
    ) -> dict[str, int]:
        source = self.store.get_source(source_id)
        policy = PathPolicy(
            (source.root_path,),
            source.allowed_extensions,
            source.max_file_size,
            source.max_depth,
        )
        run_id = self.store.start_run(source_id)
        try:
            files = LocalFileConnector(source_id, source.root_path, policy).scan()
            if after_scan is not None:
                after_scan()
            return self.store.apply_scan(run_id, source_id, files)
        except Exception as exc:
            self.store.fail_run(run_id, exc)
            raise

    def resume(self, source_id: str) -> dict[str, object]:
        """Restart a failed/aborted sync from the last committed source snapshot."""
        previous_run_id = self.store.latest_recoverable_run(source_id)
        if previous_run_id is None:
            raise RuntimeError("No failed or interrupted synchronization is available to resume")
        return {"resumed_from_run_id": previous_run_id, **self.sync(source_id)}
