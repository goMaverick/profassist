"""Subject outline documents. The section order follows the faculty template."""

import io
from typing import Any

from docx import Document
from docx.shared import Pt


def _sections(body: dict[str, Any]) -> list[tuple[str, list[str]]]:
    basics = body.get("basics") or {}
    lecture = body.get("lecture") or {}
    lines = [
        (
            "Subject",
            [
                f"{basics.get('name') or 'Subject'} ({basics.get('code') or ''})",
                f"Credit points: {basics.get('credit_points') or ''}    Session: {basics.get('session') or ''} {basics.get('year') or ''}",
                f"Duration: {basics.get('duration') or ''}    Delivery: {basics.get('delivery_mode') or ''}",
                f"Prerequisites: {basics.get('prerequisites') or 'None'}",
            ],
        ),
        (
            "Lecture information and educator",
            [
                f"{lecture.get('day') or ''} {lecture.get('time') or ''}  {lecture.get('location') or ''}",
                f"Educator: {lecture.get('educator_name') or ''}",
                f"Office: {lecture.get('office') or ''}",
                f"Email: {lecture.get('email') or ''}",
                f"Consultation: {lecture.get('consultation') or ''}",
            ],
        ),
        ("1. Subject description", [body.get("description") or ""]),
        (
            "2. Program learning outcomes",
            [f"{item.get('code')}  {item.get('text')}" for item in body.get("plos") or []],
        ),
        (
            "Course learning outcomes and the map to program outcomes",
            [
                f"{item.get('code')}  {item.get('text')}  -> {', '.join(item.get('plos') or [])}"
                for item in body.get("clos") or []
            ],
        ),
        (
            "3. Subject schedule",
            [
                f"Week {item.get('week')}: {item.get('topic')}  [{', '.join(item.get('lo_codes') or [])}]  {item.get('session_type')}  {item.get('delivery')}  {item.get('assessment_note')}"
                for item in body.get("weeks") or []
            ],
        ),
        (
            "4. Recommended readings",
            [f"{index}. {text}" for index, text in enumerate(body.get("readings") or [], start=1)],
        ),
        (
            "5. Assessment",
            [
                f"{item.get('number')} {item.get('name')} ({item.get('task_type')})  {item.get('weight')}%  due {item.get('due')}  LOs {', '.join(item.get('lo_codes') or [])}"
                for item in body.get("tasks") or []
            ],
        ),
    ]
    for task in body.get("tasks") or []:
        criteria = task.get("criteria") or []
        lines.append(
            (
                f"{task.get('number')} {task.get('name')}",
                [task.get("brief") or ""]
                + [f"{row.get('name')} ({row.get('weight')}%)" for row in criteria],
            )
        )
    lines.append(
        (
            "6. Policies",
            [f"{item.get('title')}: {item.get('body')}" for item in body.get("policies") or []],
        )
    )
    return lines


def render_docx(body: dict[str, Any]) -> bytes:
    document = Document()
    logo = _logo_path()
    if logo:
        document.add_picture(logo, width=Pt(140))
    document.add_heading("Postgraduate subject outline", level=0)
    basics = body.get("basics") or {}
    document.add_paragraph(basics.get("name") or "Subject").runs[0].font.size = Pt(16)
    for title, paragraphs in _sections(body):
        document.add_heading(title, level=1)
        for paragraph in paragraphs:
            if paragraph:
                document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def render_pdf(body: dict[str, Any]) -> bytes:
    import fitz

    document = fitz.open()
    blocks: list[str] = ["Postgraduate subject outline", ""]
    for title, paragraphs in _sections(body):
        blocks.append(title)
        blocks.extend(paragraph for paragraph in paragraphs if paragraph)
        blocks.append("")
    text = "\n".join(blocks)
    # Keep each page inside a text box so lines do not run off the page.
    size = 11
    chunk: list[str] = []
    height = 0
    for line in text.splitlines():
        wrapped = _wrap(line, 90)
        for part in wrapped:
            if height > 700:
                _add_page(document, "\n".join(chunk), size, logo=document.page_count == 0)
                chunk = []
                height = 0
            chunk.append(part)
            height += size + 4
    if chunk:
        _add_page(document, "\n".join(chunk), size, logo=document.page_count == 0)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _wrap(line: str, width: int) -> list[str]:
    if len(line) <= width:
        return [line]
    words = line.split()
    rows: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) > width:
            rows.append(current)
            current = word
        else:
            current = trial
    if current:
        rows.append(current)
    return rows or [""]


def _add_page(document, text: str, size: int, *, logo: bool = False) -> None:
    import fitz

    page = document.new_page(width=595, height=842)
    top = 48
    if logo:
        path = _logo_path()
        if path:
            page.insert_image(fitz.Rect(48, 36, 220, 84), filename=path)
            top = 96
    page.insert_textbox(
        fitz.Rect(48, top, 547, 794), text, fontsize=size, fontname="helv", color=(0.12, 0.16, 0.22)
    )


def _logo_path() -> str:
    from pathlib import Path

    path = Path(__file__).parent / "brand" / "uowd-logo.png"
    return str(path) if path.exists() else ""


def fitz_rect():
    import fitz

    return fitz.Rect(48, 48, 547, 794)
