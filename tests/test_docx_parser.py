from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._docx_fixture import ROOT_RELATIONSHIPS, write_docx

from mini_gl.parsers.docx import DocxParseError, parse_docx


class DocxParserTests(unittest.TestCase):
    def test_extracts_visible_text_without_following_external_relationships(self) -> None:
        document = b"""<?xml version="1.0" encoding="UTF-8"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>fictional</w:t><w:tab/><w:t>decision</w:t></w:r></w:p>
            <w:p><w:del><w:r><w:delText>removed secret</w:delText></w:r></w:del>
              <w:ins><w:r><w:t>visible update</w:t></w:r></w:ins></w:p>
          </w:body>
        </w:document>"""
        external_relationship = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'relationships"><Relationship Id="rId9" Type="http://schemas.'
            b'openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            b'Target="https://invalid.example/never-opened" TargetMode="External"/>'
            b"</Relationships>"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "safe.docx"
            write_docx(
                path,
                document=document,
                extras={"word/_rels/document.xml.rels": external_relationship},
            )
            original = path.read_bytes()

            parsed = parse_docx(path)

            self.assertEqual(parsed.content, "fictional\tdecision\nvisible update")
            self.assertNotIn("removed secret", parsed.content)
            self.assertEqual(parsed.paragraph_count, 2)
            self.assertEqual(parsed.encoding, "docx-ooxml")
            self.assertEqual(parsed.content_hash, hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(), original)

    def test_rejects_malformed_and_entity_bearing_xml(self) -> None:
        unsafe = b"""<?xml version="1.0"?>
        <!DOCTYPE w:document [<!ENTITY x "expanded">]>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body>
        </w:document>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            malformed = root / "malformed.docx"
            malformed.write_bytes(b"not a zip package")
            with self.assertRaisesRegex(DocxParseError, "valid DOCX"):
                parse_docx(malformed)
            entity = root / "entity.docx"
            write_docx(entity, document=unsafe)
            with self.assertRaisesRegex(DocxParseError, "declarations"):
                parse_docx(entity)

    def test_rejects_traversal_embedded_objects_and_compression_bombs(self) -> None:
        cases = {
            "traversal.docx": {"../outside.txt": b"escape"},
            "embedded.docx": {"word/embeddings/object1.bin": b"object"},
            "bomb.docx": {"word/media/payload.bin": b"A" * 1_000_000},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name, extras in cases.items():
                with self.subTest(name=name):
                    path = root / name
                    write_docx(path, extras=extras)
                    with self.assertRaises(DocxParseError):
                        parse_docx(path)

    def test_rejects_missing_or_external_main_document_relationship(self) -> None:
        external = ROOT_RELATIONSHIPS.replace(
            b'Target="word/document.xml"',
            b'Target="https://invalid.example/document.xml" TargetMode="External"',
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "external-main.docx"
            write_docx(path, root_relationships=external)
            with self.assertRaisesRegex(DocxParseError, "relationship"):
                parse_docx(path)

    def test_rejects_source_changed_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "moving.docx"
            write_docx(path)
            info = path.stat()
            changed = SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1,
            )
            with mock.patch("mini_gl.parsers.docx.os.stat", side_effect=[info, changed]):
                with self.assertRaisesRegex(DocxParseError, "changed"):
                    parse_docx(path)
