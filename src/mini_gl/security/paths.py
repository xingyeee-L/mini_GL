"""Fail-closed authorization for user-selected local paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathPolicyError(ValueError):
    """Raised when a path is outside the configured read boundary."""


@dataclass(frozen=True, slots=True)
class PathPolicy:
    roots: tuple[Path, ...]
    allowed_extensions: frozenset[str]

    def authorize(self, candidate: Path) -> Path:
        if candidate.is_symlink():
            raise PathPolicyError("Symbolic links are not allowed")

        resolved = candidate.resolve(strict=True)
        normalized_extensions = {ext.lower() for ext in self.allowed_extensions}
        if resolved.suffix.lower() not in normalized_extensions:
            raise PathPolicyError(f"File extension is not allowed: {resolved.suffix}")

        resolved_roots = tuple(root.resolve(strict=True) for root in self.roots)
        if not any(resolved == root or resolved.is_relative_to(root) for root in resolved_roots):
            raise PathPolicyError("Path is outside the authorized roots")

        return resolved
