"""Read-only connector for explicitly allowlisted local knowledge files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mini_gl.domain.models import SourceDocument
from mini_gl.parsers.docx import DocxParseError
from mini_gl.parsers.local import parse_local_file
from mini_gl.parsers.office import OfficeParseError
from mini_gl.parsers.pdf import PdfParseError
from mini_gl.parsers.structured import StructuredTextParseError
from mini_gl.parsers.text import TextParseError, UnsupportedTextEncodingError
from mini_gl.security.paths import FileSizeExceededError, PathPolicy, PathPolicyError


@dataclass(frozen=True, slots=True)
class ScannedFile:
    object_id: str
    relative_path: str
    document: SourceDocument
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SkippedFile:
    object_id: str | None
    relative_path: str
    reason: str
    size: int | None = None


@dataclass(frozen=True, slots=True)
class ScanResult:
    files: tuple[ScannedFile, ...]
    skipped: tuple[SkippedFile, ...]


def object_id_for(source_id: str, relative_path: str) -> str:
    identity = f"{source_id}\0{relative_path.replace(os.sep, '/').casefold()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class LocalFileConnector:
    def __init__(self, source_id: str, root: Path, policy: PathPolicy) -> None:
        self.source_id = source_id
        self.root = policy.authorize_root(root)
        self.policy = policy

    def scan(self) -> ScanResult:
        found: list[ScannedFile] = []
        skipped: list[SkippedFile] = []
        self._scan_directory(self.root, 0, found, skipped)
        return ScanResult(
            tuple(sorted(found, key=lambda item: item.relative_path.casefold())),
            tuple(sorted(skipped, key=lambda item: item.relative_path.casefold())),
        )

    def _scan_directory(
        self,
        directory: Path,
        depth: int,
        found: list[ScannedFile],
        skipped: list[SkippedFile],
    ) -> None:
        if self.policy._is_link_or_reparse(directory):
            raise PathPolicyError(f"Links and reparse points are not allowed: {directory}")
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise PathPolicyError(f"Unable to scan directory: {directory}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(self.root).as_posix()
            if self.policy._is_link_or_reparse(path):
                is_directory = entry.is_dir(follow_symlinks=False)
                object_id = None
                if not is_directory and path.suffix.lower() in {
                    ext.lower() for ext in self.policy.allowed_extensions
                }:
                    object_id = object_id_for(self.source_id, relative)
                skipped.append(
                    SkippedFile(object_id, relative, "link_or_reparse_point")
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                if depth >= self.policy.max_depth:
                    skipped.append(
                        SkippedFile(
                            None,
                            path.relative_to(self.root).as_posix(),
                            "maximum_recursion_depth",
                        )
                    )
                    continue
                self._scan_directory(path, depth + 1, found, skipped)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if path.suffix.lower() not in {ext.lower() for ext in self.policy.allowed_extensions}:
                continue
            object_id = object_id_for(self.source_id, relative)
            try:
                authorized = self.policy.authorize(path)
            except FileSizeExceededError:
                skipped.append(
                    SkippedFile(
                        object_id,
                        relative,
                        "maximum_file_size",
                        entry.stat(follow_symlinks=False).st_size,
                    )
                )
                continue
            try:
                parsed = parse_local_file(authorized)
            except UnsupportedTextEncodingError:
                skipped.append(
                    SkippedFile(
                        object_id,
                        relative,
                        "unsupported_text_encoding",
                        authorized.stat().st_size,
                    )
                )
                continue
            except (
                DocxParseError,
                OfficeParseError,
                PdfParseError,
                StructuredTextParseError,
                TextParseError,
            ) as exc:
                reason = "parser_safety_rejection"
                if isinstance(exc, PdfParseError):
                    reason = "pdf_parse_rejected"
                elif isinstance(exc, DocxParseError):
                    reason = "docx_parse_rejected"
                elif isinstance(exc, OfficeParseError):
                    reason = "office_parse_rejected"
                skipped.append(
                    SkippedFile(
                        object_id,
                        relative,
                        reason,
                        authorized.stat().st_size,
                    )
                )
                continue
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
