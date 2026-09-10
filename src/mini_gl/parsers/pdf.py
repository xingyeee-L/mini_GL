"""Read-only, bounded PDF text extraction with active-content rejection."""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_PDF_PAGES = 1_000
MAX_EXTRACTED_CHARS = 5_000_000
BLOCKED_PDF_NAMES = re.compile(
    rb"/(?:JavaScript|JS|EmbeddedFiles|Filespec|Launch|OpenAction|AA)(?:\s|[/<>()\[\]]|$)"
)


class PdfParseError(ValueError):
    """Raised when a PDF is unsafe, malformed, encrypted, or changes during reading."""


@dataclass(frozen=True, slots=True)
class ParsedPdf:
    content: str
    content_hash: str
    encoding: str
    size: int
    stat_result: os.stat_result
    page_count: int


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def parse_pdf(path: Path) -> ParsedPdf:
    """Extract page text without executing actions, opening attachments, or using a network."""
    before = os.stat(path, follow_symlinks=False)
    try:
        with path.open("rb") as stream:
            raw = stream.read()
    except OSError as exc:
        raise PdfParseError(f"Unable to read source: {path.name}") from exc
    after = os.stat(path, follow_symlinks=False)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        raise PdfParseError("Source changed while it was being read")
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-4_096:]:
        raise PdfParseError("File is not a complete PDF document")
    if BLOCKED_PDF_NAMES.search(raw):
        raise PdfParseError("PDF active content, launch actions, or attachments are not allowed")
    try:
        from pypdf import PdfReader, apply_configuration
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover - packaging/install failure
        raise PdfParseError("PDF support requires the pinned pypdf runtime dependency") from exc
    try:
        with apply_configuration(
            maximum_declared_stream_length=16_000_000,
            array_based_stream_maximum_output_length=16_000_000,
            jbig2_maximum_output_length=16_000_000,
            lzw_maximum_output_length=16_000_000,
            run_length_maximum_output_length=16_000_000,
            zlib_maximum_output_length=16_000_000,
            zlib_maximum_recovery_input_length=2_000_000,
            flate_maximum_columns=100_000,
            flate_maximum_row_length=2_000_000,
            image_maximum_buffer_size=16_000_000,
            xmp_maximum_input_length=1_000_000,
            xmp_maximum_element_count=20_000,
            page_tree_maximum_entries=2_000,
            page_tree_maximum_depth=50,
            xform_maximum_invocations_per_extraction=1_000,
            jbig2dec_binary=None,
        ):
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise PdfParseError("Encrypted PDF files are not supported")
            page_count = len(reader.pages)
            if page_count > MAX_PDF_PAGES:
                raise PdfParseError("PDF contains too many pages")
            pages: list[str] = []
            total_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").replace("\r\n", "\n").replace(
                    "\r", "\n"
                )
                total_chars += len(text)
                if total_chars > MAX_EXTRACTED_CHARS:
                    raise PdfParseError("PDF extracted text exceeds the safety limit")
                cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
                if cleaned:
                    pages.append(f"[Page {page_number}]\n{cleaned}")
    except PdfParseError:
        raise
    except (PdfReadError, OSError, RuntimeError, RecursionError, ValueError) as exc:
        raise PdfParseError("PDF is malformed or could not be safely parsed") from exc
    return ParsedPdf(
        content="\n\n".join(pages),
        content_hash=hashlib.sha256(raw).hexdigest(),
        encoding="pdf-text",
        size=len(raw),
        stat_result=after,
        page_count=page_count,
    )
