"""Single allowlisted dispatch boundary for local knowledge files."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mini_gl.parsers.docx import parse_docx
from mini_gl.parsers.office import parse_pptx, parse_xlsx
from mini_gl.parsers.pdf import parse_pdf
from mini_gl.parsers.structured import parse_structured_text

PLAIN_TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".rst",
        ".log",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".tex",
        ".sql",
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".sh",
        ".ps1",
        ".bat",
        ".cmd",
    }
)
STRUCTURED_TEXT_EXTENSIONS = frozenset(
    {".csv", ".tsv", ".json", ".jsonl", ".html", ".htm", ".xml"}
)
OFFICE_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})
PDF_EXTENSIONS = frozenset({".pdf"})
SUPPORTED_EXTENSIONS = frozenset(
    PLAIN_TEXT_EXTENSIONS
    | STRUCTURED_TEXT_EXTENSIONS
    | OFFICE_EXTENSIONS
    | PDF_EXTENSIONS
)


@dataclass(frozen=True, slots=True)
class ParsedLocalFile:
    content: str
    content_hash: str
    encoding: str
    size: int
    stat_result: os.stat_result
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_local_file(path: Path) -> ParsedLocalFile:
    """Dispatch only extensions that passed the source's explicit allowlist."""
    extension = path.suffix.casefold()
    if extension == ".docx":
        parsed = parse_docx(path)
        return ParsedLocalFile(
            parsed.content,
            parsed.content_hash,
            parsed.encoding,
            parsed.size,
            parsed.stat_result,
            "docx-ooxml-v1",
            {"paragraph_count": parsed.paragraph_count},
        )
    if extension == ".xlsx":
        parsed_office = parse_xlsx(path)
        return ParsedLocalFile(
            parsed_office.content,
            parsed_office.content_hash,
            parsed_office.encoding,
            parsed_office.size,
            parsed_office.stat_result,
            "xlsx-ooxml-v1",
            {"sheet_count": parsed_office.section_count},
        )
    if extension == ".pptx":
        parsed_office = parse_pptx(path)
        return ParsedLocalFile(
            parsed_office.content,
            parsed_office.content_hash,
            parsed_office.encoding,
            parsed_office.size,
            parsed_office.stat_result,
            "pptx-ooxml-v1",
            {"slide_count": parsed_office.section_count},
        )
    if extension == ".pdf":
        parsed_pdf = parse_pdf(path)
        return ParsedLocalFile(
            parsed_pdf.content,
            parsed_pdf.content_hash,
            parsed_pdf.encoding,
            parsed_pdf.size,
            parsed_pdf.stat_result,
            "pdf-pypdf-v1",
            {"page_count": parsed_pdf.page_count},
        )
    if extension in PLAIN_TEXT_EXTENSIONS | STRUCTURED_TEXT_EXTENSIONS:
        parsed_text = parse_structured_text(path)
        parser = (
            "structured-text-v1"
            if extension in STRUCTURED_TEXT_EXTENSIONS
            else "plain-text-v1"
        )
        return ParsedLocalFile(
            parsed_text.content,
            parsed_text.content_hash,
            parsed_text.encoding,
            parsed_text.size,
            parsed_text.stat_result,
            parser,
        )
    raise ValueError(f"Unsupported local file extension: {extension or '<none>'}")
