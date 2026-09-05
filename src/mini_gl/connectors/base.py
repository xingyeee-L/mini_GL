"""Connector contracts. Implementations must never mutate their sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Iterator, Protocol


class ChangeKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    source_id: str
    object_id: str
    kind: ChangeKind
    observed_at: datetime
    path: Path | None = None
    content_hash: str | None = None


class Connector(Protocol):
    def scan(self) -> Iterator[ChangeEvent]:
        """Yield idempotent change observations without modifying the source."""
        ...

