from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfWriter
from tests._common_file_fixtures import write_pdf, write_pptx, write_xlsx

from mini_gl.parsers.office import OfficeParseError, parse_pptx, parse_xlsx
from mini_gl.parsers.pdf import PdfParseError, parse_pdf
from mini_gl.parsers.structured import StructuredTextParseError, parse_structured_text


class StructuredTextParserTests(unittest.TestCase):
    def test_csv_html_json_and_xml_are_normalized_without_active_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "table.csv"
            csv_path.write_text("name,value\nfictional,42", encoding="utf-8")
            html = root / "page.html"
            html.write_text(
                "<h1>Visible heading</h1><script>hidden command</script><p>Visible body</p>",
                encoding="utf-8",
            )
            json_path = root / "data.json"
            json_path.write_text('{"decision": "fictional"}', encoding="utf-8")
            xml = root / "data.xml"
            xml.write_text("<root><item>fictional XML</item></root>", encoding="utf-8")

            self.assertIn("fictional\t42", parse_structured_text(csv_path).content)
            html_content = parse_structured_text(html).content
            self.assertIn("Visible heading", html_content)
            self.assertNotIn("hidden command", html_content)
            self.assertIn("fictional", parse_structured_text(json_path).content)
            self.assertEqual(parse_structured_text(xml).content, "fictional XML")

    def test_malformed_json_and_xml_entities_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            broken = root / "broken.json"
            broken.write_text("{", encoding="utf-8")
            entity = root / "entity.xml"
            entity.write_text(
                '<!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>',
                encoding="utf-8",
            )
            with self.assertRaises(StructuredTextParseError):
                parse_structured_text(broken)
            with self.assertRaises(StructuredTextParseError):
                parse_structured_text(entity)


class OfficeParserTests(unittest.TestCase):
    def test_xlsx_extracts_cached_visible_values_without_executing_formulas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "safe.xlsx"
            write_xlsx(path)
            original = hashlib.sha256(path.read_bytes()).hexdigest()

            parsed = parse_xlsx(path)

            self.assertIn("[Sheet: Plan]", parsed.content)
            self.assertIn("fictional spreadsheet decision", parsed.content)
            self.assertIn("C1: 2", parsed.content)
            self.assertNotIn("1+1", parsed.content)
            self.assertEqual(parsed.section_count, 1)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)

    def test_pptx_extracts_slide_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "safe.pptx"
            write_pptx(path)
            parsed = parse_pptx(path)
            self.assertEqual(
                parsed.content, "[Slide 1]\nfictional presentation decision"
            )
            self.assertEqual(parsed.section_count, 1)

    def test_office_embedded_objects_and_compression_bombs_fail_closed(self) -> None:
        cases = {
            "embedded.xlsx": {"xl/embeddings/object.bin": b"payload"},
            "bomb.pptx": {"ppt/media/bomb.bin": b"A" * 1_000_000},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            embedded = root / "embedded.xlsx"
            write_xlsx(embedded, extras=cases["embedded.xlsx"])
            bomb = root / "bomb.pptx"
            write_pptx(bomb, extras=cases["bomb.pptx"])
            with self.assertRaises(OfficeParseError):
                parse_xlsx(embedded)
            with self.assertRaises(OfficeParseError):
                parse_pptx(bomb)


class PdfParserTests(unittest.TestCase):
    def test_pdf_extracts_text_and_preserves_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "safe.pdf"
            write_pdf(path)
            original = path.read_bytes()

            parsed = parse_pdf(path)

            self.assertIn("fictional pdf decision", parsed.content)
            self.assertEqual(parsed.page_count, 1)
            self.assertEqual(path.read_bytes(), original)

    def test_active_content_malformed_and_encrypted_pdf_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active.pdf"
            write_pdf(active)
            active.write_bytes(active.read_bytes().replace(b"/Catalog", b"/Catalog /JavaScript"))
            broken = root / "broken.pdf"
            broken.write_bytes(b"%PDF-1.7\nnot complete")
            encrypted = root / "encrypted.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.encrypt("fictional-password")
            with encrypted.open("wb") as stream:
                writer.write(stream)

            with self.assertRaises(PdfParseError):
                parse_pdf(active)
            with self.assertRaises(PdfParseError):
                parse_pdf(broken)
            with self.assertRaises(PdfParseError):
                parse_pdf(encrypted)

    def test_pdf_changed_during_read_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "moving.pdf"
            write_pdf(path)
            info = path.stat()
            changed = list(info)
            changed[8] = info.st_mtime + 1
            changed_info = type(info)(changed)
            with mock.patch("mini_gl.parsers.pdf.os.stat", side_effect=[info, changed_info]):
                with self.assertRaises(PdfParseError):
                    parse_pdf(path)
