"""Local, bounded automatic synchronization for explicitly authorized sources."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mini_gl.indexing.embeddings import EmbeddingProvider
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
from mini_gl.storage.sqlite import SQLiteStore

FREQUENCY_DELAYS = {"hourly": timedelta(hours=1), "daily": timedelta(days=1)}


def next_run_time(frequency: str, *, after: datetime | None = None) -> str | None:
    if frequency == "manual":
        return None
    if frequency not in FREQUENCY_DELAYS:
        raise ValueError("Schedule frequency must be manual, hourly, or daily")
    current = after or datetime.now(UTC)
    return (current + FREQUENCY_DELAYS[frequency]).isoformat()


def common_folder_candidates(home: Path | None = None) -> list[dict[str, object]]:
    """Return metadata for the three user-named roots without scanning their contents."""
    root = (home or Path.home()).absolute()
    folders = (
        ("documents", "文档", "Documents"),
        ("downloads", "下载", "Downloads"),
        ("desktop", "桌面", "Desktop"),
    )
    return [
        {
            "key": key,
            "label": label,
            "path": str(root / directory),
            "available": (root / directory).is_dir(),
        }
        for key, label, directory in folders
    ]


def on_battery_power() -> bool:
    """Best-effort Windows power check; unknown states do not block synchronization."""
    if not hasattr(ctypes, "windll"):
        return False

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ac_line_status", ctypes.c_ubyte),
            ("battery_flag", ctypes.c_ubyte),
            ("battery_life_percent", ctypes.c_ubyte),
            ("reserved", ctypes.c_ubyte),
            ("battery_life_time", ctypes.c_ulong),
            ("battery_full_life_time", ctypes.c_ulong),
        ]

    status = SystemPowerStatus()
    kernel32 = ctypes.windll.kernel32
    if not int(kernel32.GetSystemPowerStatus(ctypes.byref(status))):
        return False
    return bool(status.ac_line_status == 0)


class AutoSyncScheduler:
    """Poll due schedules while the local application is running."""

    def __init__(
        self,
        database: Path,
        provider_factory: Callable[[], EmbeddingProvider],
        *,
        poll_seconds: float = 30.0,
        battery_check: Callable[[], bool] = on_battery_power,
    ) -> None:
        self.database = database
        self.provider_factory = provider_factory
        self.poll_seconds = max(1.0, poll_seconds)
        self.battery_check = battery_check
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._provider: EmbeddingProvider | None = None
        self.last_loop_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mini-gl-auto-sync", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self.poll_seconds + 1, 5))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_due_once()
            except Exception as exc:
                # Keep only the exception class in memory; never retain paths or document text.
                self.last_loop_error = type(exc).__name__
            if self._stop.wait(self.poll_seconds):
                return

    def run_due_once(self, now: datetime | None = None) -> list[dict[str, object]]:
        current = now or datetime.now(UTC)
        with SQLiteStore(self.database, recover_interrupted=False) as store:
            schedules = store.due_source_schedules(current.isoformat())
        results: list[dict[str, object]] = []
        for schedule in schedules:
            source_id = str(schedule["source_id"])
            frequency = str(schedule["frequency"])
            started_at = datetime.now(UTC).isoformat()
            next_at = next_run_time(frequency, after=current)
            if next_at is None:
                raise RuntimeError("Enabled automatic schedule has no next run")
            if bool(schedule["pause_on_battery"]) and self.battery_check():
                with SQLiteStore(self.database, recover_interrupted=False) as store:
                    store.record_schedule_result(
                        source_id,
                        started_at=started_at,
                        finished_at=datetime.now(UTC).isoformat(),
                        status="SKIPPED",
                        next_run_at=(current + timedelta(minutes=15)).isoformat(),
                        error="Paused while running on battery power",
                    )
                results.append({"source_id": source_id, "status": "SKIPPED"})
                continue
            try:
                with SQLiteStore(self.database, recover_interrupted=False) as store:
                    sync = IngestionService(store).sync(source_id)
                    lexical = (
                        LexicalSearchService(store).sync(source_id)
                        if bool(schedule["auto_lexical"])
                        else None
                    )
                    vector = None
                    if bool(schedule["auto_vector"]):
                        if self._provider is None:
                            self._provider = self.provider_factory()
                        vector = VectorSearchService(store, self._provider).sync(source_id)
                    store.record_schedule_result(
                        source_id,
                        started_at=started_at,
                        finished_at=datetime.now(UTC).isoformat(),
                        status="SUCCEEDED",
                        next_run_at=next_at,
                    )
                results.append(
                    {
                        "source_id": source_id,
                        "status": "SUCCEEDED",
                        "sync": sync,
                        "lexical": lexical,
                        "vector": vector,
                    }
                )
            except Exception as exc:
                with SQLiteStore(self.database, recover_interrupted=False) as store:
                    store.record_schedule_result(
                        source_id,
                        started_at=started_at,
                        finished_at=datetime.now(UTC).isoformat(),
                        status="FAILED",
                        next_run_at=next_at,
                        error=str(exc),
                    )
                results.append({"source_id": source_id, "status": "FAILED"})
        return results
