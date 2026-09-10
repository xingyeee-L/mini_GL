"""Strict extraction from macro-free XLSX and PPTX OOXML packages."""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

MAX_ARCHIVE_ENTRIES = 4_096
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_EXTRACTED_CHARS = 5_000_000
MAX_VISIBLE_ITEMS = 1_000_000

CONTENT_TYPES = "[Content_Types].xml"
ROOT_RELATIONSHIPS = "_rels/.rels"
XLSX_MAIN = "xl/workbook.xml"
PPTX_MAIN = "ppt/presentation.xml"
XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
BLOCKED_NAME_FRAGMENTS = (
    "/activex/",
    "/embeddings/",
    "/oleobjects/",
    "vbaproject.bin",
)


class OfficeParseError(ValueError):
    """Raised when an Office package is unsafe, malformed, or changes while read."""


@dataclass(frozen=True, slots=True)
class ParsedOffice:
    content: str
    content_hash: str
    encoding: str
    size: int
    stat_result: os.stat_result
    section_count: int


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def _read_stable(path: Path) -> tuple[bytes, os.stat_result]:
    before = os.stat(path, follow_symlinks=False)
    try:
        with path.open("rb") as stream:
            raw = stream.read()
    except OSError as exc:
        raise OfficeParseError(f"Unable to read source: {path.name}") from exc
    after = os.stat(path, follow_symlinks=False)
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        raise OfficeParseError("Source changed while it was being read")
    return raw, after


def _safe_xml(raw: bytes, part_name: str) -> ElementTree.Element:
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise OfficeParseError(f"Office XML declarations are not allowed: {part_name}")
    try:
        return ElementTree.fromstring(raw)  # noqa: S314
    except (ElementTree.ParseError, RecursionError) as exc:
        raise OfficeParseError(f"Office XML is malformed: {part_name}") from exc


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
        raise OfficeParseError("Office package contains an invalid path")
    if normalized in seen:
        raise OfficeParseError("Office package contains duplicate paths")
    seen.add(normalized)
    framed = f"/{normalized}"
    if any(fragment in framed for fragment in BLOCKED_NAME_FRAGMENTS):
        raise OfficeParseError("Office macros, ActiveX, and embedded objects are not allowed")
    if info.flag_bits & 0x1:
        raise OfficeParseError("Encrypted Office package entries are not supported")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise OfficeParseError("Office package links are not allowed")
    if info.file_size > MAX_ENTRY_BYTES:
        raise OfficeParseError("Office package entry exceeds the safety limit")
    if info.file_size and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
        raise OfficeParseError("Office package compression ratio exceeds the safety limit")


def _validate_package(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise OfficeParseError("Office package contains too many entries")
    total_size = 0
    seen: set[str] = set()
    for info in members:
        _validate_member(info, seen)
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise OfficeParseError("Office package uncompressed size exceeds the safety limit")
    try:
        corrupt = archive.testzip()
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OfficeParseError("Office package integrity check failed") from exc
    if corrupt is not None:
        raise OfficeParseError("Office package contains a corrupt entry")


def _read_xml(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise OfficeParseError(f"Office package is missing required part: {name}") from exc
    if info.file_size > MAX_XML_BYTES:
        raise OfficeParseError(f"Office XML part exceeds the safety limit: {name}")
    try:
        raw = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OfficeParseError(f"Unable to read Office package part: {name}") from exc
    if len(raw) != info.file_size:
        raise OfficeParseError(f"Office package part size changed while reading: {name}")
    return raw


def _find_content_type(root: ElementTree.Element, main_part: str, expected: str) -> None:
    for node in root.iter():
        if (
            _local_name(node.tag) == "Override"
            and node.attrib.get("PartName") == f"/{main_part}"
            and node.attrib.get("ContentType") == expected
        ):
            return
    raise OfficeParseError("Office package main content type is not allowed")


def _relationship_id(node: ElementTree.Element) -> str | None:
    for key, value in node.attrib.items():
        if key.startswith("{") and _local_name(key) == "id":
            return value
    return None


def _resolve_target(base_part: str, target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        resolved = posixpath.normpath(target.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        raise OfficeParseError("Office relationship escapes the package")
    return resolved


def _relationships(
    archive: zipfile.ZipFile, relationship_part: str, base_part: str
) -> dict[str, tuple[str, str, bool]]:
    root = _safe_xml(_read_xml(archive, relationship_part), relationship_part)
    output: dict[str, tuple[str, str, bool]] = {}
    for node in root.iter():
        if _local_name(node.tag) != "Relationship":
            continue
        relation_id = node.attrib.get("Id")
        target = node.attrib.get("Target")
        relation_type = node.attrib.get("Type", "")
        external = node.attrib.get("TargetMode", "Internal") == "External"
        if not relation_id or not target:
            raise OfficeParseError("Office relationship is incomplete")
        if relation_id in output:
            raise OfficeParseError("Office relationship IDs must be unique")
        resolved = target if external else _resolve_target(base_part, target)
        output[relation_id] = (relation_type, resolved, external)
    return output


def _validate_root(archive: zipfile.ZipFile, main_part: str, content_type: str) -> None:
    types = _safe_xml(_read_xml(archive, CONTENT_TYPES), CONTENT_TYPES)
    _find_content_type(types, main_part, content_type)
    relationships = _relationships(archive, ROOT_RELATIONSHIPS, "")
    if not any(
        relation_type.endswith("/officeDocument")
        and target == main_part
        and not external
        for relation_type, target, external in relationships.values()
    ):
        raise OfficeParseError("Office main document relationship is missing or unsafe")


def _main_relationship_part(main_part: str) -> str:
    parent = posixpath.dirname(main_part)
    name = posixpath.basename(main_part)
    return f"{parent}/_rels/{name}.rels"


def _extract_xlsx(archive: zipfile.ZipFile) -> tuple[str, int]:
    _validate_root(archive, XLSX_MAIN, XLSX_CONTENT_TYPE)
    workbook = _safe_xml(_read_xml(archive, XLSX_MAIN), XLSX_MAIN)
    relationships = _relationships(
        archive, _main_relationship_part(XLSX_MAIN), XLSX_MAIN
    )
    shared_strings: list[str] = []
    for relation_type, target, external in relationships.values():
        if relation_type.endswith("/sharedStrings") and not external:
            shared = _safe_xml(_read_xml(archive, target), target)
            for item in shared.iter():
                if _local_name(item.tag) == "si":
                    shared_strings.append(
                        "".join(
                            node.text or ""
                            for node in item.iter()
                            if _local_name(node.tag) == "t"
                        )
                    )
    sections: list[str] = []
    total_chars = 0
    visible_items = 0
    for sheet in workbook.iter():
        if _local_name(sheet.tag) != "sheet":
            continue
        name = sheet.attrib.get("name", "Sheet")
        relation_id = _relationship_id(sheet)
        relation = relationships.get(relation_id or "")
        if relation is None or not relation[0].endswith("/worksheet") or relation[2]:
            raise OfficeParseError("Spreadsheet worksheet relationship is missing or unsafe")
        target = relation[1]
        worksheet = _safe_xml(_read_xml(archive, target), target)
        lines = [f"[Sheet: {name}]"]
        for cell in worksheet.iter():
            if _local_name(cell.tag) != "c":
                continue
            visible_items += 1
            if visible_items > MAX_VISIBLE_ITEMS:
                raise OfficeParseError("Spreadsheet contains too many cells")
            cell_type = cell.attrib.get("t")
            value_nodes = [node for node in cell if _local_name(node.tag) == "v"]
            inline = "".join(
                node.text or ""
                for node in cell.iter()
                if _local_name(node.tag) == "t"
            )
            raw_value = value_nodes[0].text or "" if value_nodes else inline
            if cell_type == "s" and raw_value:
                try:
                    value = shared_strings[int(raw_value)]
                except (IndexError, ValueError) as exc:
                    raise OfficeParseError("Spreadsheet shared string index is invalid") from exc
            elif cell_type == "b":
                value = "TRUE" if raw_value == "1" else "FALSE"
            else:
                value = raw_value
            value = value.strip()
            if not value:
                continue
            reference = cell.attrib.get("r", "cell")
            line = f"{reference}: {value}"
            total_chars += len(line)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise OfficeParseError("Spreadsheet extracted text exceeds the safety limit")
            lines.append(line)
        sections.append("\n".join(lines))
    return "\n\n".join(sections), len(sections)


def _extract_pptx(archive: zipfile.ZipFile) -> tuple[str, int]:
    _validate_root(archive, PPTX_MAIN, PPTX_CONTENT_TYPE)
    presentation = _safe_xml(_read_xml(archive, PPTX_MAIN), PPTX_MAIN)
    relationships = _relationships(
        archive, _main_relationship_part(PPTX_MAIN), PPTX_MAIN
    )
    slides: list[str] = []
    total_chars = 0
    for node in presentation.iter():
        if _local_name(node.tag) != "sldId":
            continue
        relation_id = _relationship_id(node)
        relation = relationships.get(relation_id or "")
        if relation is None or not relation[0].endswith("/slide") or relation[2]:
            raise OfficeParseError("Presentation slide relationship is missing or unsafe")
        target = relation[1]
        slide = _safe_xml(_read_xml(archive, target), target)
        visible = [
            (item.text or "").strip()
            for item in slide.iter()
            if _local_name(item.tag) == "t" and (item.text or "").strip()
        ]
        if len(visible) > MAX_VISIBLE_ITEMS:
            raise OfficeParseError("Presentation contains too many text items")
        body = "\n".join(visible)
        total_chars += len(body)
        if total_chars > MAX_EXTRACTED_CHARS:
            raise OfficeParseError("Presentation extracted text exceeds the safety limit")
        slides.append(f"[Slide {len(slides) + 1}]\n{body}".rstrip())
    return "\n\n".join(slides), len(slides)


def _parse_office(path: Path, kind: str) -> ParsedOffice:
    raw, info = _read_stable(path)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            _validate_package(archive)
            content, section_count = (
                _extract_xlsx(archive) if kind == "xlsx" else _extract_pptx(archive)
            )
    except zipfile.BadZipFile as exc:
        raise OfficeParseError("File is not a valid Office package") from exc
    return ParsedOffice(
        content=content,
        content_hash=hashlib.sha256(raw).hexdigest(),
        encoding=f"{kind}-ooxml",
        size=len(raw),
        stat_result=info,
        section_count=section_count,
    )


def parse_xlsx(path: Path) -> ParsedOffice:
    return _parse_office(path, "xlsx")


def parse_pptx(path: Path) -> ParsedOffice:
    return _parse_office(path, "pptx")
