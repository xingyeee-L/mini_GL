"""Bounded normalization for common text-based knowledge files."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from mini_gl.parsers.text import ParsedText, TextParseError, parse_text

MAX_STRUCTURED_ITEMS = 200_000
MAX_FIELD_CHARS = 1_000_000


class StructuredTextParseError(TextParseError):
    """Raised when a structured text file is malformed or exceeds safe limits."""


class _VisibleHTMLParser(HTMLParser):
    _BLOCKED = frozenset({"script", "style", "template", "noscript"})
    _BREAKS = frozenset(
        {
            "address",
            "article",
            "br",
            "div",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "li",
            "main",
            "p",
            "section",
            "td",
            "th",
            "tr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked_depth = 0
        self.items = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.items += 1
        if self.items > MAX_STRUCTURED_ITEMS:
            raise StructuredTextParseError("HTML contains too many elements")
        lowered = tag.casefold()
        if lowered in self._BLOCKED:
            self.blocked_depth += 1
        elif lowered in self._BREAKS and self.blocked_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self._BLOCKED:
            self.blocked_depth = max(0, self.blocked_depth - 1)
        elif lowered in self._BREAKS and self.blocked_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.blocked_depth == 0:
            self.parts.append(data)


def _clean_lines(content: str) -> str:
    return "\n".join(line.strip() for line in content.splitlines() if line.strip())


def _parse_delimited(parsed: ParsedText, delimiter: str) -> ParsedText:
    try:
        rows = csv.reader(parsed.content.splitlines(), delimiter=delimiter, strict=True)
        output: list[str] = []
        count = 0
        for row in rows:
            count += 1
            if count > MAX_STRUCTURED_ITEMS:
                raise StructuredTextParseError("Delimited file contains too many rows")
            if len(row) > 4_096 or any(len(field) > MAX_FIELD_CHARS for field in row):
                raise StructuredTextParseError("Delimited file exceeds field limits")
            output.append("\t".join(field.strip() for field in row))
    except csv.Error as exc:
        raise StructuredTextParseError("Delimited file is malformed") from exc
    return replace(parsed, content="\n".join(output))


def _parse_json(parsed: ParsedText, *, lines: bool) -> ParsedText:
    try:
        if lines:
            count = 0
            for line in parsed.content.splitlines():
                if not line.strip():
                    continue
                json.loads(line)
                count += 1
                if count > MAX_STRUCTURED_ITEMS:
                    raise StructuredTextParseError("JSON Lines file contains too many records")
        else:
            json.loads(parsed.content)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise StructuredTextParseError("JSON content is malformed or too deeply nested") from exc
    return parsed


def _parse_html(parsed: ParsedText) -> ParsedText:
    parser = _VisibleHTMLParser()
    try:
        parser.feed(parsed.content)
        parser.close()
    except (AssertionError, RecursionError) as exc:
        raise StructuredTextParseError("HTML content is malformed") from exc
    return replace(parsed, content=_clean_lines("".join(parser.parts)))


def _parse_xml(parsed: ParsedText) -> ParsedText:
    upper = parsed.content.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise StructuredTextParseError("XML document type and entity declarations are not allowed")
    try:
        root = ElementTree.fromstring(parsed.content)  # noqa: S314
    except (ElementTree.ParseError, RecursionError) as exc:
        raise StructuredTextParseError("XML content is malformed") from exc
    parts: list[str] = []
    for count, node in enumerate(root.iter(), start=1):
        if count > MAX_STRUCTURED_ITEMS:
            raise StructuredTextParseError("XML contains too many elements")
        if node.text and node.text.strip():
            parts.append(node.text.strip())
        if node.tail and node.tail.strip():
            parts.append(node.tail.strip())
    return replace(parsed, content="\n".join(parts))


def parse_structured_text(path: Path) -> ParsedText:
    """Parse one text-based file without loading external resources or executing content."""
    parsed = parse_text(path)
    extension = path.suffix.casefold()
    if extension == ".csv":
        return _parse_delimited(parsed, ",")
    if extension == ".tsv":
        return _parse_delimited(parsed, "\t")
    if extension == ".json":
        return _parse_json(parsed, lines=False)
    if extension == ".jsonl":
        return _parse_json(parsed, lines=True)
    if extension in {".html", ".htm"}:
        return _parse_html(parsed)
    if extension == ".xml":
        return _parse_xml(parsed)
    return parsed
