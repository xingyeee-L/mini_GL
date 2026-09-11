"""Safe, local-only SQLite backup and restore operations."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mini_gl.security.paths import FILE_ATTRIBUTE_REPARSE_POINT


class DatabaseMaintenanceError(RuntimeError):
    """Raised when a database maintenance operation cannot complete safely."""


def backup_database(database: Path, destination: Path) -> dict[str, object]:
    """Create a consistent, verified snapshot without modifying the live database."""
    source = _existing_regular_file(database, "Database")
    target = _new_target(destination)
    try:
        return _copy_verified(source, target, operation="backup")
    except sqlite3.DatabaseError as exc:
        raise DatabaseMaintenanceError("SQLite backup failed integrity validation") from exc


def restore_database(backup: Path, destination: Path) -> dict[str, object]:
    """Restore a verified snapshot into a new path; existing files are never replaced."""
    source = _existing_regular_file(backup, "Backup")
    try:
        _check_database(source)
    except sqlite3.DatabaseError as exc:
        raise DatabaseMaintenanceError("Backup is not a valid SQLite database") from exc
    target = _new_target(destination)
    try:
        return _copy_verified(source, target, operation="restore")
    except sqlite3.DatabaseError as exc:
        raise DatabaseMaintenanceError("SQLite restore failed integrity validation") from exc


def create_managed_backup(database: Path) -> dict[str, object]:
    """Create a timestamped snapshot inside the database's application-owned backup folder."""
    source = _existing_regular_file(database, "Database")
    directory = source.parent / "backups"
    if directory.exists():
        if not directory.is_dir():
            raise DatabaseMaintenanceError("Managed backup path is not a directory")
        _reject_links(directory)
    else:
        _reject_links(directory.parent)
        directory.mkdir()
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination = directory / f"mini-gl-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"
    return backup_database(source, destination)


def list_managed_backups(database: Path) -> list[dict[str, object]]:
    """List only verified application-owned backup files; never scans user source folders."""
    directory = database.absolute().parent / "backups"
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise DatabaseMaintenanceError("Managed backup path is not a directory")
    _reject_links(directory)
    backups: list[dict[str, object]] = []
    for path in directory.iterdir():
        _reject_links(path)
        if not path.is_file() or path.suffix.lower() != ".sqlite3":
            continue
        info = path.stat()
        backups.append(
            {
                "name": path.name,
                "path": str(path.resolve(strict=True)),
                "size": info.st_size,
                "modified_at": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
            }
        )
    backups.sort(key=lambda item: (str(item["modified_at"]), str(item["name"])), reverse=True)
    return backups


def _copy_verified(source: Path, target: Path, *, operation: str) -> dict[str, object]:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_connection: sqlite3.Connection | None = None
    try:
        target_connection = sqlite3.connect(target)
        source_connection.backup(target_connection)
        target_connection.commit()
        _check_connection(target_connection)
    except Exception:
        if target_connection is not None:
            target_connection.close()
            target_connection = None
        target.unlink(missing_ok=True)
        raise
    finally:
        source_connection.close()
        if target_connection is not None:
            target_connection.close()
    return {
        "operation": operation,
        "path": str(target),
        "size": target.stat().st_size,
        "sha256": _sha256(target),
        "integrity": "ok",
    }


def _check_database(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        _check_connection(connection)
    finally:
        connection.close()


def _check_connection(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA quick_check").fetchall()
    if rows != [("ok",)]:
        raise DatabaseMaintenanceError("SQLite integrity check failed")


def _existing_regular_file(path: Path, label: str) -> Path:
    absolute = path.absolute()
    if not absolute.exists() or not absolute.is_file():
        raise DatabaseMaintenanceError(f"{label} must be an existing regular file")
    _reject_links(absolute)
    return absolute.resolve(strict=True)


def _new_target(path: Path) -> Path:
    absolute = path.absolute()
    if absolute.exists():
        raise DatabaseMaintenanceError("Destination already exists; overwrite is forbidden")
    parent = absolute.parent
    if not parent.exists() or not parent.is_dir():
        raise DatabaseMaintenanceError("Destination parent must be an existing directory")
    _reject_links(parent)
    return absolute


def _reject_links(path: Path) -> None:
    current = path
    while True:
        info = os.lstat(current)
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise DatabaseMaintenanceError("Links and reparse points are not allowed")
        if current.parent == current:
            return
        current = current.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
