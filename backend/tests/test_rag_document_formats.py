"""PPTX and HTML ingestion alongside the existing PDF/DOCX paths."""

import asyncio
import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.profassist.storage import extract_text
from app.services.rag.config import DocumentExtensions, RAGSettings, get_supported_formats
from app.services.rag.documents import (
    DocumentProcessor,
    HtmlDocumentParser,
    PptxDocumentParser,
    html_to_text,
)


def _pptx_bytes() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Week 1: Campus energy"
    slide.placeholders[1].text = "Lecture body about sensors."
    slide.notes_slide.notes_text_frame.text = "Remember the reading."

    table_slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = table_slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(2)).table
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Sample"
    table.cell(1, 1).text = "42"

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_paragraph("Word paragraph stays readable.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF page stays readable.")
    data = document.tobytes()
    document.close()
    return data


def _processor() -> DocumentProcessor:
    return DocumentProcessor(RAGSettings())


def test_supported_formats_include_pptx_and_html() -> None:
    values = {extension.value for extension in DocumentExtensions}
    assert {".pptx", ".html", ".htm"} <= values
    allowed = set(RAGSettings().allowed_extensions)
    assert {
        DocumentExtensions.PPTX,
        DocumentExtensions.HTML,
        DocumentExtensions.HTM,
    } <= allowed
    supported = get_supported_formats()
    assert {".pptx", ".html", ".htm"} <= supported
    assert ".pptx" in get_supported_formats("liteparse")
    assert {".html", ".htm"} <= get_supported_formats("llamaparse")


def test_pptx_parser_extracts_titles_text_tables_and_notes(tmp_path: Path) -> None:
    path = tmp_path / "deck.pptx"
    path.write_bytes(_pptx_bytes())

    document = asyncio.run(PptxDocumentParser().parse(path))

    assert len(document.pages) == 2
    first = document.pages[0].content
    assert "Week 1: Campus energy" in first
    assert "Lecture body about sensors." in first
    assert "Remember the reading." in first
    second = document.pages[1].content
    assert "Metric | Value" in second
    assert "Sample | 42" in second


def test_html_parser_keeps_structure_and_drops_scripts(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Hidden</title><style>.x{color:red}</style></head>"
        "<body><h1>Campus energy</h1><p>Lecture notes.</p>"
        "<ul><li>Sensor one</li><li>Sensor two</li></ul>"
        "<script>alert('nope')</script></body></html>",
        encoding="utf-8",
    )

    document = asyncio.run(HtmlDocumentParser().parse(path))
    content = document.pages[0].content

    assert "Campus energy" in content
    assert "Lecture notes." in content
    assert "- Sensor one" in content
    assert "alert" not in content
    assert "color:red" not in content
    assert "Hidden" not in content


def test_html_to_text_strips_style_and_script() -> None:
    text = html_to_text(
        "<style>p{}</style><h2>Heading</h2><p>Body text</p>"
        "<script>window.x = 1</script><li>Item</li>"
    )

    assert "Heading" in text
    assert "Body text" in text
    assert "Item" in text
    assert "window.x" not in text
    assert "p{}" not in text


def test_processor_routes_pptx_and_html(tmp_path: Path) -> None:
    pptx_path = tmp_path / "deck.pptx"
    pptx_path.write_bytes(_pptx_bytes())
    html_path = tmp_path / "page.html"
    html_path.write_text("<h1>Title</h1><p>Body</p>", encoding="utf-8")

    processor = _processor()
    pptx_document = asyncio.run(processor.process_file(pptx_path))
    html_document = asyncio.run(processor.process_file(html_path))

    assert pptx_document.chunked_pages
    assert any("Campus energy" in chunk.chunk_content for chunk in pptx_document.chunked_pages)
    assert html_document.chunked_pages
    assert any("Body" in chunk.chunk_content for chunk in html_document.chunked_pages)


def test_processor_keeps_docx_and_pdf_working(tmp_path: Path) -> None:
    docx_path = tmp_path / "notes.docx"
    docx_path.write_bytes(_docx_bytes())
    pdf_path = tmp_path / "notes.pdf"
    pdf_path.write_bytes(_pdf_bytes())

    processor = _processor()
    docx_document = asyncio.run(processor.process_file(docx_path))
    pdf_document = asyncio.run(processor.process_file(pdf_path))

    assert any("Word paragraph" in chunk.chunk_content for chunk in docx_document.chunked_pages)
    assert any("PDF page" in chunk.chunk_content for chunk in pdf_document.chunked_pages)


def test_storage_extract_text_reads_pptx_and_html() -> None:
    pptx_text = extract_text("deck.pptx", _pptx_bytes())
    html_text = extract_text(
        "page.htm",
        b"<h1>Heading</h1><p>Visible</p><script>secret()</script>",
    )

    assert "Week 1: Campus energy" in pptx_text
    assert "Metric | Value" in pptx_text
    assert "Remember the reading." in pptx_text
    assert "Heading" in html_text
    assert "Visible" in html_text
    assert "secret" not in html_text


def test_storage_extract_text_keeps_docx_and_pdf_working() -> None:
    assert "Word paragraph" in extract_text("notes.docx", _docx_bytes())
    assert "PDF page" in extract_text("notes.pdf", _pdf_bytes())


@pytest.mark.anyio
async def test_add_material_accepts_html(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist import service as prof_service

    org_id = uuid.uuid4()
    course_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def _course(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=course_id, organization_id=org_id)

    async def _names(*args: Any, **kwargs: Any) -> list[str]:
        return []

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(prof_service, "_course", _course)
    monkeypatch.setattr(prof_service, "_names", _names)
    monkeypatch.setattr(prof_service, "_remember_pii", _noop)
    monkeypatch.setattr(prof_service, "extract_text", lambda filename, data: "HTML lecture notes.")
    monkeypatch.setattr(prof_service, "save_bytes", lambda *args, **kwargs: "key")
    monkeypatch.setattr(prof_service, "index_chunks", lambda *args, **kwargs: True)
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    result = await prof_service.add_material(
        db, org_id, course_id, user_id, "page.html", b"<h1>HTML lecture notes.</h1>"
    )

    assert result["status"] == "ready"
    assert result["filename"] == "page.html"


def test_unsupported_extension_is_still_rejected(tmp_path: Path) -> None:
    path = tmp_path / "notes.rtf"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file type"):
        asyncio.run(_processor().process_file(path))
