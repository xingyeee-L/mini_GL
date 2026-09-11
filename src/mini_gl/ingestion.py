"""Application service for source registration and synchronization."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mini_gl.connectors.local_files import LocalFileConnector
from mini_gl.parsers.local import SUPPORTED_EXTENSIONS
from mini_gl.security.paths import DEFAULT_MAX_DEPTH, DEFAULT_MAX_FILE_SIZE, PathPolicy
from mini_gl.storage.sqlite import RegisteredSource, SQLiteStore

DEFAULT_EXTENSIONS = SUPPORTED_EXTENSIONS


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
    ) -> dict[str, object]:
        source = self.store.get_source(source_id)
        policy = PathPolicy(
            (source.root_path,),
            source.allowed_extensions,
            source.max_file_size,
            source.max_depth,
        )
        run_id = self.store.start_run(source_id)
        try:
            scan = LocalFileConnector(source_id, source.root_path, policy).scan()
            if after_scan is not None:
                after_scan()
            result: dict[str, object] = dict(
                self.store.apply_scan(
                    run_id,
                    source_id,
                    list(scan.files),
                    retained_object_ids={
                        item.object_id for item in scan.skipped if item.object_id is not None
                    },
                    retained_path_prefixes={
                        item.relative_path
                        for item in scan.skipped
                        if item.object_id is None
                        and item.reason
                        in {"maximum_recursion_depth", "link_or_reparse_point"}
                    },
                )
            )
            if scan.skipped:
                result["skipped"] = len(scan.skipped)
                warnings: list[dict[str, object]] = []
                for item in scan.skipped:
                    warning: dict[str, object] = {
                        "relative_path": item.relative_path,
                        "reason": item.reason,
                    }
                    if item.size is not None:
                        warning["size"] = item.size
                    warnings.append(warning)
                result["warnings"] = warnings
            return result
        except Exception as exc:
            self.store.fail_run(run_id, exc)
            raise

    def resume(self, source_id: str) -> dict[str, object]:
        """Restart a failed/aborted sync from the last committed source snapshot."""
        previous_run_id = self.store.latest_recoverable_run(source_id)
        if previous_run_id is None:
            raise RuntimeError("No failed or interrupted synchronization is available to resume")
        return {"resumed_from_run_id": previous_run_id, **self.sync(source_id)}
