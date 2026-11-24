"""Assessment brief documents rendered from the structured body.

The body is deliberately made of arrays so a draft can be stored, retrieved and
RAG-indexed without a bespoke schema per course. The section labels follow the
Assessment 2 template. Missing fields render empty; the renderer does not
invent sections or copy.
"""

from __future__ import annotations

import io
from typing import Any

# Label and key order is the template order. Unknown keys stay empty.
from app.profassist.assignment_data import CLASS_DETAILS as CLASS_FIELDS

FIELD_HEADERS = ("Field", "Value")
PROBLEM_HEADERS = ("Problem", "Description")
REPORT_HEADERS = ("#", "Section", "Guidelines")

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
MARGIN = 48.0
CELL_PAD = 4.0


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _strings(body: dict[str, Any], key: str) -> list[str]:
    return [_text(item) for item in body.get(key) or [] if _text(item)]


def _dicts(body: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in body.get(key) or [] if isinstance(item, dict)]


def _class_rows(body: dict[str, Any]) -> list[list[str]]:
    details = body.get("class_details") or {}
    return [[label, _text(details.get(key))] for label, key in CLASS_FIELDS]


def _problem_rows(body: dict[str, Any]) -> list[list[str]]:
    return [
        [_text(item.get("problem")), _text(item.get("description"))]
        for item in _dicts(body, "problem_choices")
    ]


def _section_rows(body: dict[str, Any]) -> list[list[str]]:
    return [
        [
            _text(item.get("number")),
            _text(item.get("section")),
            _text(item.get("guidelines")),
        ]
        for item in _dicts(body, "report_sections")
    ]


def _technical_report(body: dict[str, Any]) -> str:
    """The paragraph under 3.1. Prefer the matching deliverable, then class details."""
    for item in _dicts(body, "deliverables"):
        title = _text(item.get("title"))
        if "technical report" in title.lower():
            return _text(item.get("description"))
    details = body.get("class_details") or {}
    length = _text(details.get("report_length"))
    due = _text(details.get("report_due"))
    parts = []
    if length:
        parts.append(f"Report length: {length}.")
    if due:
        parts.append(f"Report due: {due}.")
    return " ".join(parts)


def _logo_path() -> str:
    from pathlib import Path

    path = Path(__file__).parent / "brand" / "uowd-logo.png"
    return str(path) if path.exists() else ""


def _add_table(
    document: Any,
    headers: tuple[str, ...],
    rows: list[list[str]],
    widths: tuple[Any, ...],
) -> Any:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    for index, cell in enumerate(table.rows[0].cells):
        cell.text = headers[index]
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for values in rows:
        cells = table.add_row().cells
        for index, cell in enumerate(cells):
            cell.text = values[index] if index < len(values) else ""
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = widths[index]
    return table


def _add_deliverable(document: Any, item: dict[str, Any]) -> None:
    paragraph = document.add_paragraph()
    title = _text(item.get("title"))
    description = _text(item.get("description"))
    if title:
        run = paragraph.add_run(title)
        run.bold = True
        if description:
            paragraph.add_run(": ")
    if description:
        paragraph.add_run(description)


def render_docx(body: dict[str, Any]) -> bytes:
    """Render the brief as a Word document. Logo, title, details, then sections 1-3.1."""
    from docx import Document
    from docx.shared import Inches, Pt

    document = Document()
    logo = _logo_path()
    if logo:
        document.add_picture(logo, width=Pt(140))

    details = body.get("class_details") or {}
    document.add_heading(
        _text(details.get("assessment")) or "Assessment brief",
        level=0,
    )
    _add_table(document, FIELD_HEADERS, _class_rows(body), (Inches(1.6), Inches(4.6)))

    document.add_heading("1 Overview", level=1)
    for paragraph in _strings(body, "overview"):
        document.add_paragraph(paragraph)

    document.add_heading("2 Choosing Your Problem", level=1)
    _add_table(document, PROBLEM_HEADERS, _problem_rows(body), (Inches(2.1), Inches(4.1)))

    document.add_heading("3 Deliverables", level=1)
    for item in _dicts(body, "deliverables"):
        _add_deliverable(document, item)

    document.add_heading("3.1 Technical report", level=1)
    document.add_paragraph(_technical_report(body))
    _add_table(
        document,
        REPORT_HEADERS,
        _section_rows(body),
        (Inches(0.45), Inches(1.85), Inches(3.9)),
    )

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _ascii(value: str) -> str:
    """Base-14 Helvetica is Latin-1. Fold typographic punctuation so text stays readable."""
    return (
        value.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2022", "-")
        .replace("\u00a0", " ")
    )


def _wrap(value: str, width: float, fontname: str, size: float) -> list[str]:
    import pymupdf

    lines: list[str] = []
    for block in _ascii(value).split("\n"):
        words = block.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if pymupdf.get_text_length(trial, fontname=fontname, fontsize=size) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
            while pymupdf.get_text_length(word, fontname=fontname, fontsize=size) > width:
                cut = len(word)
                while (
                    cut > 1
                    and pymupdf.get_text_length(word[:cut], fontname=fontname, fontsize=size)
                    > width
                ):
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return lines or [""]


class _Pdf:
    """A small flowing writer. Tables repeat their header across pages and split tall rows."""

    def __init__(self) -> None:
        import pymupdf

        self.pymupdf = pymupdf
        self.document = pymupdf.open()
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN

    @property
    def width(self) -> float:
        return PAGE_WIDTH - 2 * MARGIN

    def _new_page(self) -> None:
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN

    def _ensure(self, height: float) -> None:
        if self.y + height > PAGE_HEIGHT - MARGIN:
            self._new_page()

    def logo(self, path: str) -> None:
        if not path:
            return
        rect = self.pymupdf.Rect(MARGIN, MARGIN, MARGIN + 170, MARGIN + 30.2)
        self.page.insert_image(rect, filename=path)
        self.y = MARGIN + 44

    def heading(
        self, value: str, size: float = 14.0, before: float = 12.0, after: float = 4.0
    ) -> None:
        self.y += before
        lines = _wrap(value, self.width, "hebo", size)
        self._ensure(len(lines) * size * 1.4 + after)
        for line in lines:
            self._ensure(size * 1.4)
            self.page.insert_text(
                (MARGIN, self.y + size),
                line,
                fontsize=size,
                fontname="hebo",
                color=(0.10, 0.14, 0.20),
            )
            self.y += size * 1.4
        self.y += after

    def paragraph(
        self, value: str, size: float = 10.5, bold: bool = False, after: float = 6.0
    ) -> None:
        font = "hebo" if bold else "helv"
        lines = _wrap(value, self.width, font, size)
        for line in lines:
            self._ensure(size * 1.4)
            self.page.insert_text(
                (MARGIN, self.y + size),
                line,
                fontsize=size,
                fontname=font,
                color=(0.12, 0.16, 0.22),
            )
            self.y += size * 1.4
        self.y += after

    def table(
        self,
        headers: tuple[str, ...],
        rows: list[list[str]],
        widths: tuple[float, ...],
        size: float = 9.5,
    ) -> None:
        columns = self._fit_widths(widths)
        self._header(columns, headers, size)
        for values in rows:
            self._row(columns, values, headers, size)
        self.y += 6

    def _fit_widths(self, widths: tuple[float, ...]) -> list[float]:
        total = sum(widths)
        if total <= self.width:
            return list(widths)
        scale = self.width / total
        return [width * scale for width in widths]

    def _header(self, columns: list[float], headers: tuple[str, ...], size: float) -> None:
        chunks = [
            _wrap(
                headers[index] if index < len(headers) else "",
                columns[index] - 2 * CELL_PAD,
                "hebo",
                size,
            )
            for index in range(len(columns))
        ]
        height = max(len(chunk) for chunk in chunks) * size * 1.3 + 2 * CELL_PAD
        self._ensure(height)
        self._draw(columns, chunks, size, height, fill=(0.90, 0.93, 0.97))

    def _row(
        self,
        columns: list[float],
        values: list[str],
        headers: tuple[str, ...],
        size: float,
    ) -> None:
        lines = [
            _wrap(
                values[index] if index < len(values) else "",
                columns[index] - 2 * CELL_PAD,
                "helv",
                size,
            )
            for index in range(len(columns))
        ]
        while True:
            available = PAGE_HEIGHT - MARGIN - self.y
            if available < size * 1.3 + 2 * CELL_PAD:
                self._new_page()
                self._header(columns, headers, size)
                continue
            max_lines = max(1, int((available - 2 * CELL_PAD) // (size * 1.3)))
            chunk = [part[:max_lines] for part in lines]
            height = max(len(part) for part in chunk) * size * 1.3 + 2 * CELL_PAD
            self._draw(columns, chunk, size, height)
            lines = [part[max_lines:] for part in lines]
            if not any(lines):
                return
            self._new_page()
            self._header(columns, headers, size)

    def _draw(
        self,
        columns: list[float],
        chunks: list[list[str]],
        size: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
    ) -> None:
        top = self.y
        x = MARGIN
        for index, width in enumerate(columns):
            rect = self.pymupdf.Rect(x, top, x + width, top + height)
            self.page.draw_rect(
                rect,
                color=(0.70, 0.72, 0.76),
                fill=fill,
                width=0.5,
            )
            line_y = top + CELL_PAD
            for line in chunks[index]:
                self.page.insert_text(
                    (x + CELL_PAD, line_y + size),
                    line,
                    fontsize=size,
                    fontname="hebo" if fill else "helv",
                    color=(0.12, 0.16, 0.22),
                )
                line_y += size * 1.3
            x += width
        self.y = top + height


def render_pdf(body: dict[str, Any]) -> bytes:
    """Render the same brief with PyMuPDF, with multi-page tables."""
    writer = _Pdf()
    writer.logo(_logo_path())

    details = body.get("class_details") or {}
    writer.heading(
        _text(details.get("assessment")) or "Assessment brief",
        size=20,
        before=0,
        after=10,
    )
    writer.table(FIELD_HEADERS, _class_rows(body), (130.0, 369.0), size=9.5)

    writer.heading("1 Overview")
    for paragraph in _strings(body, "overview"):
        writer.paragraph(paragraph)

    writer.heading("2 Choosing Your Problem")
    writer.table(PROBLEM_HEADERS, _problem_rows(body), (150.0, 349.0), size=9.5)

    writer.heading("3 Deliverables")
    for item in _dicts(body, "deliverables"):
        title = _text(item.get("title"))
        description = _text(item.get("description"))
        if title and description:
            writer.paragraph(f"{title}: {description}", bold=True)
        elif title or description:
            writer.paragraph(title or description, bold=bool(title))

    writer.heading("3.1 Technical report")
    writer.paragraph(_technical_report(body))
    writer.table(REPORT_HEADERS, _section_rows(body), (32.0, 155.0, 312.0), size=9.0)

    data = writer.document.tobytes()
    writer.document.close()
    return data
