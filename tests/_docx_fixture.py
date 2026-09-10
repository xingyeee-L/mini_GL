"""Small fictional OOXML packages used only by parser tests."""

from __future__ import annotations

import zipfile
from collections.abc import Mapping
from pathlib import Path

CONTENT_TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    b'<Default Extension="rels" '
    b'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    b'<Default Extension="xml" ContentType="application/xml"/>\n'
    b'<Override PartName="/word/document.xml" '
    b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
    b'document.main+xml"/>\n'
    b"</Types>"
)

ROOT_RELATIONSHIPS = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
    b'<Relationship Id="rId1" '
    b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    b'officeDocument" Target="word/document.xml"/>\n'
    b"</Relationships>"
)

DEFAULT_DOCUMENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>fictional project decision</w:t></w:r></w:p>
  </w:body>
</w:document>"""


def write_docx(
    path: Path,
    *,
    document: bytes = DEFAULT_DOCUMENT,
    content_types: bytes = CONTENT_TYPES,
    root_relationships: bytes = ROOT_RELATIONSHIPS,
    extras: Mapping[str, bytes] | None = None,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("word/document.xml", document)
        for name, content in (extras or {}).items():
            archive.writestr(name, content)
