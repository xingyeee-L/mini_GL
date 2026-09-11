"""Desktop product readiness and application-owned cleanup inventory."""

from __future__ import annotations

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def application_version() -> str:
    try:
        return version("mini-gl")
    except PackageNotFoundError:
        return "0.1.0-dev"


def product_status(database: Path, project_root: Path | None = None) -> dict[str, object]:
    """Return metadata-only readiness; never inspect registered source contents."""
    root = (project_root or Path.cwd()).absolute()
    database_path = database.absolute()
    backups = database_path.parent / "backups"
    backup_count = 0
    latest_backup: str | None = None
    if backups.is_dir() and not backups.is_symlink():
        candidates = [
            item
            for item in backups.iterdir()
            if item.is_file() and not item.is_symlink() and item.suffix.lower() == ".sqlite3"
        ]
        backup_count = len(candidates)
        if candidates:
            latest_backup = max(candidates, key=lambda item: item.stat().st_mtime).name
    checks = {
        "python_supported": sys.version_info >= (3, 11),
        "launcher_available": (root / "start-mini-gl.cmd").is_file(),
        "runtime_lock_available": (root / "requirements-runtime.lock").is_file(),
        "database_parent_writable": _directory_writable(database_path.parent),
        "database_initialized": database_path.is_file(),
        "backup_available": backup_count > 0,
    }
    required = (
        "python_supported",
        "launcher_available",
        "runtime_lock_available",
        "database_parent_writable",
    )
    return {
        "version": application_version(),
        "platform": sys.platform,
        "installed_python": sys.executable,
        "database": str(database_path),
        "backup_count": backup_count,
        "latest_backup": latest_backup,
        "checks": checks,
        "desktop_ready": all(checks[key] for key in required),
        "setup_complete": all(checks.values()),
    }


def uninstall_inventory(database: Path, project_root: Path | None = None) -> dict[str, object]:
    """List only application-owned derived paths; never include registered source roots."""
    root = (project_root or Path.cwd()).absolute()
    database_path = database.absolute()
    candidates = (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        database_path.parent / "backups",
        root / ".venv",
    )
    items = []
    for path in candidates:
        items.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "kind": "directory" if path.is_dir() else "file",
                "scope": "application_owned",
            }
        )
    return {
        "confirmation": "UNINSTALL MINI_GL",
        "items": items,
        "preserves_registered_sources": True,
        "note": "This preview never deletes files and never enumerates source folders.",
    }


def _directory_writable(path: Path) -> bool:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current.is_dir() and os.access(current, os.W_OK)
