"""Strict, bounded extraction of visible text from untrusted DOCX packages."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

MAX_ARCHIVE_ENTRIES = 2_048
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200

CONTENT_TYPES = "[Content_Types].xml"
ROOT_RELATIONSHIPS = "_rels/.rels"
MAIN_DOCUMENT = "word/document.xml"
MAIN_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "application/vnd.ms-word.document.main+xml",
    }
)
BLOCKED_PART_PREFIXES = ("word/activex/", "word/embeddings/")
BLOCKED_PARTS = frozenset({"word/vbaproject.bin"})


class DocxParseError(ValueError):
    """Raised when a DOCX package is unsafe, malformed, or changes while read."""


@dataclass(frozen=True, slots=True)
class ParsedDocx:
    content: str
    content_hash: str
    encoding: str
    size: int
    stat_result: os.stat_result
    paragraph_count: int


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _safe_xml(raw: bytes, part_name: str) -> ElementTree.Element:
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise DocxParseError(f"DOCX XML declarations are not allowed: {part_name}")
    try:
        # ElementTree stays dependency-free; size limits plus the explicit DTD/entity
        # rejection above close the XML expansion paths flagged by generic scanners.
        return ElementTree.fromstring(raw)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise DocxParseError(f"DOCX XML is malformed: {part_name}") from exc


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def _validate_member(info: zipfile.ZipInfo, seen: set[str]) -> None:
    name = info.filename
    pure = PurePosixPath(name)
    normalized = name.casefold()
    if (
        not name
        or len(name) > 512
        or "\\" in name
        or name.startswith("/")
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise DocxParseError("DOCX contains an invalid package path")
    if normalized in seen:
        raise DocxParseError("DOCX contains duplicate package paths")
    seen.add(normalized)
    if info.flag_bits & 0x1:
        raise DocxParseError("Encrypted DOCX package entries are not supported")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise DocxParseError("DOCX package links are not allowed")
    if normalized in BLOCKED_PARTS or normalized.startswith(BLOCKED_PART_PREFIXES):
        raise DocxParseError("DOCX macros, ActiveX, and embedded objects are not allowed")
    if info.file_size > MAX_ENTRY_BYTES:
        raise DocxParseError("DOCX package entry exceeds the safety limit")
    if info.file_size and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
        raise DocxParseError("DOCX package compression ratio exceeds the safety limit")


def _read_xml(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise DocxParseError(f"DOCX is missing required part: {name}") from exc
    if info.file_size > MAX_XML_BYTES:
        raise DocxParseError(f"DOCX XML part exceeds the safety limit: {name}")
    try:
        raw = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise DocxParseError(f"Unable to read DOCX part: {name}") from exc
    if len(raw) != info.file_size:
        raise DocxParseError(f"DOCX part size changed while reading: {name}")
    return raw


def _validate_package(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise DocxParseError("DOCX contains too many package entries")
    seen: set[str] = set()
    total_size = 0
    for info in members:
        _validate_member(info, seen)
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise DocxParseError("DOCX uncompressed size exceeds the safety limit")
    try:
        corrupt = archive.testzip()
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise DocxParseError("DOCX package integrity check failed") from exc
    if corrupt is not None:
        raise DocxParseError("DOCX package contains a corrupt entry")


def _validate_content_type(root: ElementTree.Element) -> None:
    for node in root.iter():
        if (
            _local_name(node.tag) == "Override"
            and node.attrib.get("PartName") == f"/{MAIN_DOCUMENT}"
            and node.attrib.get("ContentType") in MAIN_CONTENT_TYPES
        ):
            return
    raise DocxParseError("DOCX main document content type is not allowed")


def _validate_root_relationship(root: ElementTree.Element) -> None:
    for node in root.iter():
        relationship_type = node.attrib.get("Type", "")
        target = node.attrib.get("Target", "").replace("\\", "/").lstrip("/")
        if relationship_type.endswith("/officeDocument"):
            if node.attrib.get("TargetMode", "Internal") != "Internal":
                break
            if PurePosixPath(target) == PurePosixPath(MAIN_DOCUMENT):
                return
    raise DocxParseError("DOCX main document relationship is missing or unsafe")


def _visible_text(node: ElementTree.Element, *, deleted: bool = False) -> str:
    name = _local_name(node.tag)
    if name == "del":
        deleted = True
    if deleted or name in {"instrText", "delText"}:
        return ""
    if name == "t":
        return node.text or ""
    if name == "tab":
        return "\t"
    if name in {"br", "cr"}:
        return "\n"
    if name == "noBreakHyphen":
        return "-"
    return "".join(_visible_text(child, deleted=deleted) for child in node)


def _extract_document(root: ElementTree.Element) -> tuple[str, int]:
    paragraphs = [
        _visible_text(node).strip()
        for node in root.iter()
        if _local_name(node.tag) == "p"
    ]
    visible = [paragraph for paragraph in paragraphs if paragraph]
    return "\n".join(visible), len(visible)


def parse_docx(path: Path) -> ParsedDocx:
    """Read one DOCX atomically and extract only visible main-document text."""
    before = os.stat(path, follow_symlinks=False)
    try:
        with path.open("rb") as stream:
            raw = stream.read()
    except OSError as exc:
        raise DocxParseError(f"Unable to read source: {path.name}") from exc
    after = os.stat(path, follow_symlinks=False)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        raise DocxParseError("Source changed while it was being read")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            _validate_package(archive)
            content_types = _safe_xml(_read_xml(archive, CONTENT_TYPES), CONTENT_TYPES)
            relationships = _safe_xml(
                _read_xml(archive, ROOT_RELATIONSHIPS), ROOT_RELATIONSHIPS
            )
            document = _safe_xml(_read_xml(archive, MAIN_DOCUMENT), MAIN_DOCUMENT)
            _validate_content_type(content_types)
            _validate_root_relationship(relationships)
            content, paragraph_count = _extract_document(document)
    except zipfile.BadZipFile as exc:
        raise DocxParseError("File is not a valid DOCX package") from exc
    return ParsedDocx(
        content=content,
        content_hash=hashlib.sha256(raw).hexdigest(),
        encoding="docx-ooxml",
        size=len(raw),
        stat_result=after,
        paragraph_count=paragraph_count,
    )
