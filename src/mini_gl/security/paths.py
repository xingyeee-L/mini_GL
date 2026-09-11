"""Fail-closed authorization for user-selected local paths."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_MAX_DEPTH = 8
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class PathPolicyError(ValueError):
    """Raised when a path is outside the configured read boundary."""


class FileSizeExceededError(PathPolicyError):
    """Raised before opening a regular file whose metadata exceeds the configured limit."""


@dataclass(frozen=True, slots=True)
class PathPolicy:
    roots: tuple[Path, ...]
    allowed_extensions: frozenset[str]
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    max_depth: int = DEFAULT_MAX_DEPTH

    def __post_init__(self) -> None:
        if not self.roots:
            raise PathPolicyError("At least one authorized root is required")
        if not 0 <= self.max_depth <= DEFAULT_MAX_DEPTH:
            raise PathPolicyError(f"Maximum depth must be between 0 and {DEFAULT_MAX_DEPTH}")
        if not 0 < self.max_file_size <= DEFAULT_MAX_FILE_SIZE:
            raise PathPolicyError(
                f"Maximum file size must be between 1 and {DEFAULT_MAX_FILE_SIZE} bytes"
            )

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        info = os.lstat(path)
        attributes = getattr(info, "st_file_attributes", 0)
        return stat.S_ISLNK(info.st_mode) or bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)

    def authorize_root(self, root: Path) -> Path:
        absolute = root.absolute()
        if not absolute.exists() or not absolute.is_dir():
            raise PathPolicyError("Authorized root must be an existing directory")
        current = absolute
        while True:
            if self._is_link_or_reparse(current):
                raise PathPolicyError(f"Links and reparse points are not allowed: {current}")
            if current.parent == current:
                break
            current = current.parent
        return absolute.resolve(strict=True)

    def authorize(self, candidate: Path) -> Path:
        absolute = candidate.absolute()
        resolved_roots = tuple(self.authorize_root(root) for root in self.roots)
        containing_root = next(
            (root for root in resolved_roots if absolute == root or absolute.is_relative_to(root)),
            None,
        )
        if containing_root is None:
            raise PathPolicyError("Path is outside the authorized roots")

        relative = absolute.relative_to(containing_root)
        if max(0, len(relative.parts) - 1) > self.max_depth:
            raise PathPolicyError("Maximum recursion depth exceeded")

        current = containing_root
        for part in relative.parts:
            current = current / part
            if self._is_link_or_reparse(current):
                raise PathPolicyError(f"Links and reparse points are not allowed: {current}")

        resolved = absolute.resolve(strict=True)
        normalized_extensions = {ext.lower() for ext in self.allowed_extensions}
        if resolved.suffix.lower() not in normalized_extensions:
            raise PathPolicyError(f"File extension is not allowed: {resolved.suffix}")
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode):
            raise PathPolicyError("Only regular files are allowed")
        if info.st_size > self.max_file_size:
            raise FileSizeExceededError("Maximum file size exceeded")

        return resolved
