"""Subject outline documents. Section order, labels, and tables follow the faculty template."""

import io
from collections.abc import Sequence
from typing import Any

from docx import Document
from docx.shared import Inches, Pt

SUBJECT_FIELDS = (
    ("SUBJECT NAME", "name"),
    ("Course code", "code"),
    ("Section", "section"),
    ("Credit Points", "credit_points"),
    ("Year", "year"),
    ("Session", "session"),
    ("Duration", "duration"),
    ("Pre-requisite(s)", "prerequisites"),
    ("Equivalent Subject(s)", "equivalent_subjects"),
    ("Mode of Delivery", "delivery_mode"),
)

LECTURE_FIELDS = (
    ("Day", "day"),
    ("Time", "time"),
    ("Location", "location"),
    ("Educator's Name", "educator_name"),
    ("Building & Office No", "office"),
    ("E-mail Address", "email"),
    ("Consultation", "consultation"),
)

SCHEDULE_HEADERS = (
    "Week",
    "Lecture Topic(s)",
    "Learning Outcomes",
    "Session Type",
    "Delivery format",
    "Assessment",
)

RUBRIC_HEADERS = (
    "Criteria",
    "Excellent (85-100%)",
    "Good (70-84%)",
    "Satisfactory (50-69%)",
    "Needs Improvement (<50%)",
    "Weight",
)


def _value(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, list):
        return ", ".join(str(part) for part in item)
    return str(item)


def _equivalent(basics: dict[str, Any]) -> str:
    return _value(basics.get("equivalent_subjects") or basics.get("equivalent"))


def _policy_titles(body: dict[str, Any]) -> list[str]:
    items = body.get("policy_documents")
    if items is None:
        items = body.get("policies") or []
    titles = []
    for item in items or []:
        if isinstance(item, str):
            titles.append(item)
        elif isinstance(item, dict):
            titles.append(_value(item.get("title")))
    return [title for title in titles if title]


def _legacy_policies(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in body.get("policies") or [] if isinstance(item, dict) and item.get("body")
    ]


def _integrity_parts(body: dict[str, Any]) -> dict[str, Any]:
    integrity = body.get("academic_integrity") or {}
    if isinstance(integrity, str):
        return {"intro": integrity}
    return integrity


def _summary(body: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    tasks = body.get("assessment_tasks") or []
    headers = ["Learning Outcome"] + [
        f"Assessment {index} {_value(task.get('title'))} {_value(task.get('weight'))}%"
        for index, task in enumerate(tasks, start=1)
    ]
    rows = []
    for clo in body.get("clos") or []:
        code = _value(clo.get("code"))
        rows.append(
            [code] + ["X" if code in (task.get("lo_codes") or []) else "" for task in tasks]
        )
    rows.append(
        ["Group (G)/ Individual (I)"]
        + [
            "G"
            if task.get("type") == "Group"
            else "I"
            if task.get("type") == "Individual"
            else _value(task.get("type"))
            for task in tasks
        ]
    )
    rows.append(["Total Marks"] + [_value(task.get("total_marks")) for task in tasks])
    rows.append(["Due Date"] + [_value(task.get("due")) for task in tasks])
    return headers, rows


def _task_rows(task: dict[str, Any]) -> list[tuple[str, str]]:
    codes = ", ".join(str(code).replace("LO", "").strip() for code in task.get("lo_codes") or [])
    return [
        ("Type", _value(task.get("type"))),
        ("Learning Outcome Measured", codes),
        ("Total Marks", _value(task.get("total_marks"))),
        ("Weighting", f"{_value(task.get('weight'))}%"),
        ("Due Date", _value(task.get("due"))),
    ]


def _rubric_rows(task: dict[str, Any]) -> list[list[str]]:
    rows = []
    for criterion in task.get("rubric") or []:
        levels = criterion.get("levels") or {}
        rows.append(
            [
                _value(criterion.get("name")),
                _value(levels.get("advanced")),
                _value(levels.get("proficient")),
                _value(levels.get("developing")),
                _value(levels.get("beginning")),
                f"{_value(criterion.get('weight'))}%",
            ]
        )
    return rows


def _add_key_value_table(document: Any, rows: list[tuple[str, str]]) -> None:
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.autofit = False
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value or "-"
        for paragraph in cells[0].paragraphs:
            for run in paragraph.runs:
                run.bold = True
    _set_widths(table, [Inches(2.0), Inches(4.5)])


def _add_table(
    document: Any,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    widths: list[float] | None = None,
) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    for index, label in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = label
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = value or ""
    if widths:
        _set_widths(table, [Inches(width) for width in widths])


def _set_widths(table: Any, widths: Sequence[Any]) -> None:
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = width


def _add_numbered(document: Any, items: Sequence[str]) -> None:
    for index, item in enumerate(items, start=1):
        document.add_paragraph(f"{index}. {_value(item)}")


def _add_task(document: Any, task: dict[str, Any]) -> None:
    document.add_heading(f"Assessment Task: {_value(task.get('title'))}", level=3)
    _add_key_value_table(document, _task_rows(task))
    has_more = bool(task.get("deliverables") or task.get("format"))
    heading = "Overview" if has_more else "OUTLINE AND REQUIREMENTS"
    overview = task.get("overview") or []
    if overview:
        document.add_heading(heading, level=4)
        for paragraph in overview:
            document.add_paragraph(_value(paragraph))
    if task.get("deliverables"):
        document.add_heading("Deliverables", level=4)
        _add_numbered(document, task.get("deliverables") or [])
    if task.get("format"):
        document.add_heading("Format & Guidelines", level=4)
        _add_numbered(document, task.get("format") or [])
    document.add_heading("Marking Rubric", level=4)
    _add_table(
        document,
        RUBRIC_HEADERS,
        _rubric_rows(task),
        widths=[1.35, 1.05, 1.0, 0.95, 0.95, 0.6],
    )


def render_docx(body: dict[str, Any]) -> bytes:
    document = Document()
    logo = _logo_path()
    if logo:
        document.add_picture(logo, width=Pt(140))
    document.add_heading("Postgraduate subject outline", level=0)
    basics = body.get("basics") or {}
    lecture = body.get("lecture") or {}
    plos = body.get("plos") or []
    clos = body.get("clos") or []
    weeks = body.get("weeks") or []
    readings = body.get("readings") or []

    subject_name = document.add_paragraph(_value(basics.get("name")) or "Subject")
    subject_name.runs[0].font.size = Pt(16)

    document.add_heading("Subject details", level=1)
    _add_key_value_table(
        document,
        [
            (
                label,
                _equivalent(basics) if key == "equivalent_subjects" else _value(basics.get(key)),
            )
            for label, key in SUBJECT_FIELDS
        ],
    )

    document.add_heading("LECTURE INFORMATION", level=1)
    _add_key_value_table(
        document,
        [(label, _value(lecture.get(key))) for label, key in LECTURE_FIELDS],
    )

    document.add_heading("1. SUBJECT DESCRIPTION", level=1)
    document.add_paragraph(_value(body.get("description")) or "-")

    document.add_heading(
        "2. Learning Outcome and Contribution to Program learning outcomes (PLO)", level=1
    )
    if _value(body.get("program")):
        document.add_paragraph(f"Program: {_value(body.get('program'))}")
    document.add_heading("Program learning outcomes", level=2)
    _add_table(
        document,
        ["PLO", "Description"],
        [[_value(plo.get("code")), _value(plo.get("text"))] for plo in plos],
        widths=[0.9, 5.6],
    )
    document.add_heading("Map of learning outcomes to program learning outcomes", level=2)
    matrix_headers = ["LO", "Learning outcome"] + [_value(plo.get("code")) for plo in plos]
    matrix_rows = []
    for clo in clos:
        mapped = set(clo.get("plos") or [])
        matrix_rows.append(
            [_value(clo.get("code")), _value(clo.get("text"))]
            + ["X" if _value(plo.get("code")) in mapped else "" for plo in plos]
        )
    _add_table(document, matrix_headers, matrix_rows)

    document.add_heading("3. SUBJECT SCHEDULE", level=1)
    _add_table(
        document,
        list(SCHEDULE_HEADERS),
        [
            [
                _value(week.get("week")),
                _value(week.get("topic")),
                _value(week.get("lo_codes")),
                _value(week.get("session_type")),
                _value(week.get("delivery")),
                _value(week.get("assessment_note")),
            ]
            for week in weeks
        ],
        widths=[0.55, 2.05, 1.05, 0.85, 0.85, 0.85],
    )

    document.add_heading("4. SUPPORTING MATERIALS", level=1)
    document.add_paragraph(_value(body.get("supporting_intro")) or "-")
    document.add_heading("RECOMMENDED READINGS", level=2)
    _add_numbered(document, readings)
    document.add_heading("4.1 ACCESS TO SUPPORTING MATERIALS", level=2)
    document.add_paragraph(_value(body.get("supporting_access")) or "-")

    document.add_heading("5. ASSESSMENT", level=1)
    document.add_heading("5.1 ASSESSMENT OF LEARNING OUTCOMES", level=2)
    _add_table(
        document,
        ["Learning outcome", "Measures"],
        [
            [_value(row.get("lo_code")), _value(row.get("measures"))]
            for row in body.get("outcome_measures") or []
        ],
        widths=[1.3, 5.2],
    )

    document.add_heading("5.2 ASSESSMENT TASKS", level=2)
    tasks = body.get("assessment_tasks") or []
    if not tasks:
        document.add_paragraph("No assessment tasks yet.")
    else:
        summary_headers, summary_rows = _summary(body)
        _add_table(document, summary_headers, summary_rows)
        for task in tasks:
            _add_task(document, task)
    late = _value(body.get("late_submission"))
    if late:
        paragraph = document.add_paragraph()
        run = paragraph.add_run("LATE SUBMISSIONS: ")
        run.bold = True
        paragraph.add_run(late)

    document.add_heading("5.3 USING GENERATIVE AI (GENAI)", level=2)
    document.add_paragraph(_value(body.get("genai_intro")) or "-")
    _add_numbered(document, body.get("genai") or [])

    document.add_heading("5.4 GRADES AWARDED", level=2)
    document.add_paragraph(
        "The approved grades of performance and associated ranges of marks for undergraduate "
        "subjects are:"
    )
    _add_table(
        document,
        ["Grade", "Range", "Description"],
        [
            [
                _value(row.get("band") or row.get("grade")),
                _value(row.get("range")),
                _value(row.get("description")),
            ]
            for row in body.get("grades") or []
        ],
        widths=[1.8, 1.7, 3.0],
    )

    document.add_heading("5.5 SATISFACTORY COMPLETION REQUIREMENTS", level=2)
    for paragraph in body.get("satisfactory") or []:
        document.add_paragraph(_value(paragraph))
    if _value(body.get("satisfactory_note")):
        note = document.add_paragraph()
        run = note.add_run("Template note: ")
        run.bold = True
        note.add_run(_value(body.get("satisfactory_note")).removeprefix("Template note: "))

    document.add_heading("6. RELEVANT POLICIES AND DOCUMENTS", level=1)
    document.add_paragraph(_value(body.get("policy_intro")) or "-")
    _add_numbered(document, _policy_titles(body))

    document.add_heading("7. SSP & STUDIOSITY", level=1)
    document.add_paragraph(_value(body.get("ssp")) or "-")

    integrity = _integrity_parts(body)
    document.add_heading("8. ACADEMIC INTEGRITY", level=1)
    document.add_paragraph(_value(integrity.get("intro")) or "-")
    document.add_heading("8.1 TURNITIN", level=2)
    document.add_paragraph(_value(integrity.get("turnitin")) or "-")
    fields = integrity.get("turnitin_fields") or []
    if fields:
        _add_key_value_table(
            document,
            [(_value(row.get("label")), _value(row.get("value"))) for row in fields],
        )
    document.add_heading("8.2 REFERENCE & IN-TEXT CITATION", level=2)
    document.add_paragraph(_value(integrity.get("referencing")) or "-")
    document.add_heading("8.3 UOWD RULES & POLICIES", level=2)
    document.add_paragraph(_value(integrity.get("rules")) or "-")

    document.add_heading("9. ATTENDANCE REQUIREMENTS", level=1)
    document.add_paragraph(_value(body.get("attendance")) or "-")
    document.add_heading("10. SUPPLEMENTARY ASSESSMENTS", level=1)
    document.add_paragraph(_value(body.get("supplementary")) or "-")
    document.add_heading("11. Lecture Capture", level=1)
    document.add_paragraph(_value(body.get("lecture_capture")) or "-")
    document.add_heading("12. Sustainability", level=1)
    document.add_paragraph(_value(body.get("sustainability")) or "-")

    legacy = _legacy_policies(body)
    if legacy:
        document.add_heading("Appendix - Policies", level=1)
        for policy in legacy:
            document.add_heading(_value(policy.get("title")) or "Policy", level=2)
            document.add_paragraph(_value(policy.get("body")) or "-")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 48
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
BOTTOM = PAGE_HEIGHT - MARGIN
INK = (0.12, 0.16, 0.22)
GRID = (0.55, 0.6, 0.66)
HEADER_FILL = (0.92, 0.94, 0.97)


class _Pdf:
    """A small table renderer on top of PyMuPDF. Rows wrap and continue over pages."""

    def __init__(self, document: Any, fitz: Any, logo: str = "") -> None:
        self.document = document
        self.fitz = fitz
        self.logo = logo
        self.page: Any = None
        self.y = MARGIN
        self._new_page(first=True)

    def _new_page(self, *, first: bool = False) -> None:
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN
        if first and self.logo:
            self.page.insert_image(self.fitz.Rect(MARGIN, 36, MARGIN + 172, 84), filename=self.logo)
            self.y = 96

    def _ensure(self, height: float) -> None:
        if self.y + height > BOTTOM:
            self._new_page()

    def _width(self, text: str, fontname: str, size: float) -> float:
        return self.fitz.get_text_length(text, fontname=fontname, fontsize=size)

    def _wrap(self, text: str, width: float, fontname: str, size: float) -> list[str]:
        words = str(text or "").split()
        if not words:
            return [""]
        lines: list[str] = []
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if not current or self._width(trial, fontname, size) <= width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def heading(self, text: str, size: float = 13, *, before: float = 10, after: float = 4) -> None:
        lines = self._wrap(text, CONTENT_WIDTH, "hebo", size)
        height = len(lines) * (size + 2) + before + after
        self._ensure(height)
        self.y += before
        for line in lines:
            self.page.insert_text(
                (MARGIN, self.y + size), line, fontsize=size, fontname="hebo", color=INK
            )
            self.y += size + 2
        self.y += after

    def paragraph(self, text: str, size: float = 10.5, *, bold: bool = False) -> None:
        fontname = "hebo" if bold else "helv"
        lines = self._wrap(text, CONTENT_WIDTH, fontname, size)
        height = len(lines) * (size + 2) + 4
        self._ensure(height)
        for line in lines:
            self.page.insert_text(
                (MARGIN, self.y + size), line, fontsize=size, fontname=fontname, color=INK
            )
            self.y += size + 2
        self.y += 4

    def table(
        self,
        headers: Sequence[str] | None,
        rows: Sequence[Sequence[str]],
        widths: Sequence[float],
        *,
        size: float = 8.5,
        bold_first: bool = False,
    ) -> None:
        if headers:
            self._draw_row(list(headers), widths, size=size, fontname="hebo", fill=HEADER_FILL)
        for row in rows:
            self._draw_row(
                list(row),
                widths,
                size=size,
                fontname="helv",
                bold_first=bold_first,
                headers=list(headers) if headers else None,
            )

    def _wrap_row(
        self,
        cells: list[str],
        widths: Sequence[float],
        size: float,
        fontname: str,
        *,
        bold_first: bool = False,
    ) -> tuple[list[tuple[list[str], str]], float]:
        wrapped: list[tuple[list[str], str]] = []
        lines = 1
        for index, cell in enumerate(cells):
            font = "hebo" if bold_first and index == 0 else fontname
            cell_lines = self._wrap(cell, widths[index] - 6, font, size)
            wrapped.append((cell_lines, font))
            lines = max(lines, len(cell_lines))
        return wrapped, lines * (size + 2) + 6

    def _draw_row(
        self,
        cells: list[str],
        widths: Sequence[float],
        *,
        size: float,
        fontname: str,
        fill: tuple[float, float, float] | None = None,
        bold_first: bool = False,
        headers: list[str] | None = None,
    ) -> None:
        wrapped, height = self._wrap_row(cells, widths, size, fontname, bold_first=bold_first)
        if self.y + height > BOTTOM:
            self._new_page()
            if headers:
                self._draw_row(headers, widths, size=size, fontname="hebo", fill=HEADER_FILL)
        x = MARGIN
        for index, width in enumerate(widths):
            rect = self.fitz.Rect(x, self.y, x + width, self.y + height)
            self.page.draw_rect(rect, color=GRID, fill=fill, width=0.5)
            text_y = self.y + size + 3
            cell_lines, font = wrapped[index]
            for line in cell_lines:
                self.page.insert_text(
                    (x + 3, text_y), line, fontsize=size, fontname=font, color=INK
                )
                text_y += size + 2
            x += width
        self.y += height


def _pdf_numbered(pdf: _Pdf, items: Sequence[str]) -> None:
    for index, item in enumerate(items, start=1):
        pdf.paragraph(f"{index}. {_value(item)}")


def _pdf_task(pdf: _Pdf, task: dict[str, Any]) -> None:
    pdf.heading(f"Assessment Task: {_value(task.get('title'))}", size=11.5)
    pdf.table(None, _task_rows(task), [170, CONTENT_WIDTH - 170], bold_first=True)
    has_more = bool(task.get("deliverables") or task.get("format"))
    heading = "Overview" if has_more else "OUTLINE AND REQUIREMENTS"
    overview = task.get("overview") or []
    if overview:
        pdf.heading(heading, size=10.5)
        for paragraph in overview:
            pdf.paragraph(_value(paragraph))
    if task.get("deliverables"):
        pdf.heading("Deliverables", size=10.5)
        _pdf_numbered(pdf, task.get("deliverables") or [])
    if task.get("format"):
        pdf.heading("Format & Guidelines", size=10.5)
        _pdf_numbered(pdf, task.get("format") or [])
    pdf.heading("Marking Rubric", size=10.5)
    pdf.table(
        list(RUBRIC_HEADERS),
        _rubric_rows(task),
        [95, 95, 85, 80, 80, 64],
        size=7.5,
    )


def render_pdf(body: dict[str, Any]) -> bytes:
    import fitz

    basics = body.get("basics") or {}
    lecture = body.get("lecture") or {}
    plos = body.get("plos") or []
    clos = body.get("clos") or []
    weeks = body.get("weeks") or []
    readings = body.get("readings") or []

    document = fitz.open()
    pdf = _Pdf(document, fitz, _logo_path())
    pdf.heading("Postgraduate subject outline", size=16, before=0)
    pdf.heading(_value(basics.get("name")) or "Subject", size=15, before=2)

    pdf.heading("Subject details")
    pdf.table(
        None,
        [
            (
                label,
                _equivalent(basics) if key == "equivalent_subjects" else _value(basics.get(key)),
            )
            for label, key in SUBJECT_FIELDS
        ],
        [170, CONTENT_WIDTH - 170],
        bold_first=True,
    )

    pdf.heading("LECTURE INFORMATION")
    pdf.table(
        None,
        [(label, _value(lecture.get(key))) for label, key in LECTURE_FIELDS],
        [170, CONTENT_WIDTH - 170],
        bold_first=True,
    )

    pdf.heading("1. SUBJECT DESCRIPTION")
    pdf.paragraph(_value(body.get("description")) or "-")

    pdf.heading("2. Learning Outcome and Contribution to Program learning outcomes (PLO)")
    if _value(body.get("program")):
        pdf.paragraph(f"Program: {_value(body.get('program'))}")
    pdf.heading("Program learning outcomes", size=11.5)
    pdf.table(
        ["PLO", "Description"],
        [[_value(plo.get("code")), _value(plo.get("text"))] for plo in plos],
        [60, CONTENT_WIDTH - 60],
    )
    pdf.heading("Map of learning outcomes to program learning outcomes", size=11.5)
    matrix_widths: list[float] = [40, 210]
    if plos:
        share = (CONTENT_WIDTH - sum(matrix_widths)) / len(plos)
        matrix_widths.extend([share] * len(plos))
    else:
        matrix_widths = [40, CONTENT_WIDTH - 40]
    matrix_rows = []
    for clo in clos:
        mapped = set(clo.get("plos") or [])
        matrix_rows.append(
            [_value(clo.get("code")), _value(clo.get("text"))]
            + ["X" if _value(plo.get("code")) in mapped else "" for plo in plos]
        )
    pdf.table(
        ["LO", "Learning outcome"] + [_value(plo.get("code")) for plo in plos],
        matrix_rows,
        matrix_widths,
    )

    pdf.heading("3. SUBJECT SCHEDULE")
    pdf.table(
        list(SCHEDULE_HEADERS),
        [
            [
                _value(week.get("week")),
                _value(week.get("topic")),
                _value(week.get("lo_codes")),
                _value(week.get("session_type")),
                _value(week.get("delivery")),
                _value(week.get("assessment_note")),
            ]
            for week in weeks
        ],
        [40, 169, 80, 70, 70, 70],
    )

    pdf.heading("4. SUPPORTING MATERIALS")
    pdf.paragraph(_value(body.get("supporting_intro")) or "-")
    pdf.heading("RECOMMENDED READINGS", size=11.5)
    _pdf_numbered(pdf, readings)
    pdf.heading("4.1 ACCESS TO SUPPORTING MATERIALS", size=11.5)
    pdf.paragraph(_value(body.get("supporting_access")) or "-")

    pdf.heading("5. ASSESSMENT")
    pdf.heading("5.1 ASSESSMENT OF LEARNING OUTCOMES", size=11.5)
    pdf.table(
        ["Learning outcome", "Measures"],
        [
            [_value(row.get("lo_code")), _value(row.get("measures"))]
            for row in body.get("outcome_measures") or []
        ],
        [100, CONTENT_WIDTH - 100],
    )

    pdf.heading("5.2 ASSESSMENT TASKS", size=11.5)
    tasks = body.get("assessment_tasks") or []
    if not tasks:
        pdf.paragraph("No assessment tasks yet.")
    else:
        summary_headers, summary_rows = _summary(body)
        summary_widths = [70.0] + [(CONTENT_WIDTH - 70) / max(len(summary_headers) - 1, 1)] * max(
            len(summary_headers) - 1, 1
        )
        pdf.table(summary_headers, summary_rows, summary_widths, size=8)
        for task in tasks:
            _pdf_task(pdf, task)
    late = _value(body.get("late_submission"))
    if late:
        pdf.paragraph(f"LATE SUBMISSIONS: {late}", bold=True)

    pdf.heading("5.3 USING GENERATIVE AI (GENAI)", size=11.5)
    pdf.paragraph(_value(body.get("genai_intro")) or "-")
    _pdf_numbered(pdf, body.get("genai") or [])

    pdf.heading("5.4 GRADES AWARDED", size=11.5)
    pdf.paragraph(
        "The approved grades of performance and associated ranges of marks for undergraduate "
        "subjects are:"
    )
    pdf.table(
        ["Grade", "Range", "Description"],
        [
            [
                _value(row.get("band") or row.get("grade")),
                _value(row.get("range")),
                _value(row.get("description")),
            ]
            for row in body.get("grades") or []
        ],
        [130, 130, CONTENT_WIDTH - 260],
        size=8,
    )

    pdf.heading("5.5 SATISFACTORY COMPLETION REQUIREMENTS", size=11.5)
    for paragraph in body.get("satisfactory") or []:
        pdf.paragraph(_value(paragraph))
    note_text = _value(body.get("satisfactory_note"))
    if note_text:
        if note_text.lower().startswith("template note:"):
            note_text = note_text[len("template note:") :].strip()
        pdf.paragraph(f"Template note: {note_text}", size=9.5, bold=True)

    pdf.heading("6. RELEVANT POLICIES AND DOCUMENTS")
    pdf.paragraph(_value(body.get("policy_intro")) or "-")
    _pdf_numbered(pdf, _policy_titles(body))

    pdf.heading("7. SSP & STUDIOSITY")
    pdf.paragraph(_value(body.get("ssp")) or "-")

    integrity = _integrity_parts(body)
    pdf.heading("8. ACADEMIC INTEGRITY")
    pdf.paragraph(_value(integrity.get("intro")) or "-")
    pdf.heading("8.1 TURNITIN", size=11.5)
    pdf.paragraph(_value(integrity.get("turnitin")) or "-")
    fields = integrity.get("turnitin_fields") or []
    if fields:
        pdf.table(
            None,
            [(_value(row.get("label")), _value(row.get("value"))) for row in fields],
            [120, CONTENT_WIDTH - 120],
            bold_first=True,
        )
    pdf.heading("8.2 REFERENCE & IN-TEXT CITATION", size=11.5)
    pdf.paragraph(_value(integrity.get("referencing")) or "-")
    pdf.heading("8.3 UOWD RULES & POLICIES", size=11.5)
    pdf.paragraph(_value(integrity.get("rules")) or "-")

    pdf.heading("9. ATTENDANCE REQUIREMENTS")
    pdf.paragraph(_value(body.get("attendance")) or "-")
    pdf.heading("10. SUPPLEMENTARY ASSESSMENTS")
    pdf.paragraph(_value(body.get("supplementary")) or "-")
    pdf.heading("11. Lecture Capture")
    pdf.paragraph(_value(body.get("lecture_capture")) or "-")
    pdf.heading("12. Sustainability")
    pdf.paragraph(_value(body.get("sustainability")) or "-")

    legacy = _legacy_policies(body)
    if legacy:
        pdf.heading("Appendix - Policies")
        for policy in legacy:
            pdf.heading(_value(policy.get("title")) or "Policy", size=11.5)
            pdf.paragraph(_value(policy.get("body")) or "-")

    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _logo_path() -> str:
    from pathlib import Path

    path = Path(__file__).parent / "brand" / "uowd-logo.png"
    return str(path) if path.exists() else ""


def fitz_rect():
    import fitz

    return fitz.Rect(48, 48, 547, 794)
