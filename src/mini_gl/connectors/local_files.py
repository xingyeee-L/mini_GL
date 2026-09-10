"""Read-only connector for explicitly allowlisted local knowledge files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mini_gl.domain.models import SourceDocument
from mini_gl.parsers.local import parse_local_file
from mini_gl.security.paths import PathPolicy, PathPolicyError


@dataclass(frozen=True, slots=True)
class ScannedFile:
    object_id: str
    relative_path: str
    document: SourceDocument
    size: int
    mtime_ns: int


def object_id_for(source_id: str, relative_path: str) -> str:
    identity = f"{source_id}\0{relative_path.replace(os.sep, '/').casefold()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class LocalFileConnector:
    def __init__(self, source_id: str, root: Path, policy: PathPolicy) -> None:
        self.source_id = source_id
        self.root = policy.authorize_root(root)
        self.policy = policy

    def scan(self) -> list[ScannedFile]:
        found: list[ScannedFile] = []
        self._scan_directory(self.root, 0, found)
        return sorted(found, key=lambda item: item.relative_path.casefold())

    def _scan_directory(self, directory: Path, depth: int, found: list[ScannedFile]) -> None:
        if depth > self.policy.max_depth:
            raise PathPolicyError("Maximum recursion depth exceeded")
        if self.policy._is_link_or_reparse(directory):
            raise PathPolicyError(f"Links and reparse points are not allowed: {directory}")
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise PathPolicyError(f"Unable to scan directory: {directory}") from exc
        for entry in entries:
            path = Path(entry.path)
            if self.policy._is_link_or_reparse(path):
                raise PathPolicyError(f"Links and reparse points are not allowed: {path}")
            if entry.is_dir(follow_symlinks=False):
                self._scan_directory(path, depth + 1, found)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if path.suffix.lower() not in {ext.lower() for ext in self.policy.allowed_extensions}:
                continue
            authorized = self.policy.authorize(path)
            parsed = parse_local_file(authorized)
            relative = authorized.relative_to(self.root).as_posix()
            object_id = object_id_for(self.source_id, relative)
            info = parsed.stat_result
            created = datetime.fromtimestamp(info.st_ctime, UTC)
            updated = datetime.fromtimestamp(info.st_mtime, UTC)
            document = SourceDocument(
                id=f"local_file:{self.source_id}:{object_id}",
                source_type="local_file",
                source_uri=str(authorized),
                title=authorized.name,
                content=parsed.content,
                content_hash=parsed.content_hash,
                created_at=created,
                updated_at=updated,
                metadata={
                    "encoding": parsed.encoding,
                    "relative_path": relative,
                    "size": parsed.size,
                    "parser": parsed.parser,
                    **parsed.metadata,
                },
            )
            found.append(ScannedFile(object_id, relative, document, parsed.size, info.st_mtime_ns))
