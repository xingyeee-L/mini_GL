"""Strict, read-only parsing for plain text and Markdown files."""

from __future__ import annotations

import codecs
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class TextParseError(ValueError):
    """Raised when a source cannot be read consistently or decoded safely."""


@dataclass(frozen=True, slots=True)
class ParsedText:
    content: str
    content_hash: str
    encoding: str
    size: int
    stat_result: os.stat_result


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _decode(raw: bytes) -> tuple[str, str]:
    try:
        if raw.startswith(codecs.BOM_UTF8):
            return raw.decode("utf-8-sig", errors="strict"), "utf-8-sig"
        if raw.startswith(codecs.BOM_UTF16_LE):
            return raw.decode("utf-16-le", errors="strict").lstrip("\ufeff"), "utf-16-le"
        if raw.startswith(codecs.BOM_UTF16_BE):
            return raw.decode("utf-16-be", errors="strict").lstrip("\ufeff"), "utf-16-be"
        try:
            return raw.decode("utf-8", errors="strict"), "utf-8"
        except UnicodeDecodeError:
            return raw.decode("gb18030", errors="strict"), "gb18030"
    except UnicodeDecodeError as exc:
        raise TextParseError("File is not valid UTF-8, BOM-marked UTF-16, or GB18030") from exc


def parse_text(path: Path) -> ParsedText:
    before = os.stat(path, follow_symlinks=False)
    try:
        with path.open("rb") as stream:
            raw = stream.read()
    except OSError as exc:
        raise TextParseError(f"Unable to read source: {path.name}") from exc
    after = os.stat(path, follow_symlinks=False)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        raise TextParseError("Source changed while it was being read")
    content, encoding = _decode(raw)
    return ParsedText(
        content=content.replace("\r\n", "\n").replace("\r", "\n"),
        content_hash=hashlib.sha256(raw).hexdigest(),
        encoding=encoding,
        size=len(raw),
        stat_result=after,
    )
