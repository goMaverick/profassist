"""The subject outline follows the faculty template: same sections, real tables."""

import asyncio
import io
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from docx import Document

from app.profassist.outline_data import demo_outline, empty_outline
from app.profassist.outline_doc import render_docx, render_pdf


def _docx(data: bytes) -> tuple[list[str], list[list[list[str]]]]:
    document = Document(io.BytesIO(data))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    tables = [
        [[cell.text for cell in row.cells] for row in table.rows] for table in document.tables
    ]
    return paragraphs, tables


def _table(tables: list[list[list[str]]], first: str) -> list[list[str]]:
    for table in tables:
        if table and table[0] and table[0][0] == first:
            return table
    raise AssertionError(f"No table starts with {first!r}")


def _row(tables: list[list[list[str]]], first: str) -> list[str]:
    for table in tables:
        for row in table:
            if row and row[0] == first:
                return row
    raise AssertionError(f"No row starts with {first!r}")


def _all_text(data: bytes) -> str:
    paragraphs, tables = _docx(data)
    pieces = list(paragraphs)
    for table in tables:
        for row in table:
            pieces.extend(row)
    return "\n".join(pieces)


def test_docx_matches_the_full_template() -> None:
    body = demo_outline()
    data = render_docx(body)
    paragraphs, tables = _docx(data)

    for heading in (
        "Subject details",
        "LECTURE INFORMATION",
        "1. SUBJECT DESCRIPTION",
        "2. Learning Outcome and Contribution to Program learning outcomes (PLO)",
        "Program learning outcomes",
        "Map of learning outcomes to program learning outcomes",
        "3. SUBJECT SCHEDULE",
        "4. SUPPORTING MATERIALS",
        "RECOMMENDED READINGS",
        "4.1 ACCESS TO SUPPORTING MATERIALS",
        "5. ASSESSMENT",
        "5.1 ASSESSMENT OF LEARNING OUTCOMES",
        "5.2 ASSESSMENT TASKS",
        "5.3 USING GENERATIVE AI (GENAI)",
        "5.4 GRADES AWARDED",
        "5.5 SATISFACTORY COMPLETION REQUIREMENTS",
        "6. RELEVANT POLICIES AND DOCUMENTS",
        "7. SSP & STUDIOSITY",
        "8. ACADEMIC INTEGRITY",
        "8.1 TURNITIN",
        "8.2 REFERENCE & IN-TEXT CITATION",
        "8.3 UOWD RULES & POLICIES",
        "9. ATTENDANCE REQUIREMENTS",
        "10. SUPPLEMENTARY ASSESSMENTS",
        "11. Lecture Capture",
        "12. Sustainability",
    ):
        assert heading in paragraphs, heading

    subject = _table(tables, "SUBJECT NAME")
    subject_cells = [cell for row in subject for cell in row]
    assert "Course code" in subject_cells
    assert "Pre-requisite(s)" in subject_cells
    assert "Equivalent Subject(s)" in subject_cells
    assert "Mode of Delivery" in subject_cells
    assert "MAAI 903" in subject_cells

    lecture = _table(tables, "Day")
    lecture_cells = [cell for row in lecture for cell in row]
    assert "Educator's Name" in lecture_cells
    assert "Building & Office No" in lecture_cells
    assert "E-mail Address" in lecture_cells
    assert "Consultation" in lecture_cells

    assert _table(tables, "PLO")[0] == ["PLO", "Description"]
    matrix = _table(tables, "LO")
    assert matrix[0][:2] == ["LO", "Learning outcome"]
    assert "X" in [cell for row in matrix[1:] for cell in row]

    schedule = _table(tables, "Week")
    assert schedule[0] == [
        "Week",
        "Lecture Topic(s)",
        "Learning Outcomes",
        "Session Type",
        "Delivery format",
        "Assessment",
    ]
    assert len(schedule) == 12  # header plus 11 weeks
    assert schedule[-1][0] == "11"
    assert "Communication & Reflection Video" in schedule[-1][-1]

    measures = _table(tables, "Learning outcome")
    assert measures[0] == ["Learning outcome", "Measures"]
    assert [row[0] for row in measures[1:]] == [f"LO{index}" for index in range(1, 7)]
    assert "Solution architecture report" in measures[1][1]

    summary = _table(tables, "Learning Outcome")
    assert summary[0][1].startswith("Assessment 1 Workshops 25%")
    assert summary[0][2].startswith("Assessment 2 Solution Architecture Report 25%")
    assert summary[0][3].startswith("Assessment 3 Group Project: Deployable AI System 40%")
    assert summary[0][4].startswith("Assessment 4 Communication and Reflection Video 10%")
    assert any(row[0] == "LO1" and "X" in row for row in summary)
    assert _row(tables, "Group (G)/ Individual (I)")[1:] == ["I", "I", "G", "I"]
    assert _row(tables, "Total Marks")[1:] == ["100", "100", "100", "100"]
    assert _row(tables, "Due Date")[1:] == [
        "Throughout the semester",
        "Week 7",
        "Week 11",
        "Week 12",
    ]

    rubric = _table(tables, "Criteria")
    assert rubric[0] == [
        "Criteria",
        "Excellent (85-100%)",
        "Good (70-84%)",
        "Satisfactory (50-69%)",
        "Needs Improvement (<50%)",
        "Weight",
    ]
    problem = _row(tables, "Problem Definition & Business Context")
    assert problem[-1] == "15%"
    assert "measurable business impact" in problem[1]
    assert _row(tables, "Solution Design & Architecture")[-1] == "25%"
    assert _row(tables, "Data Strategy & Pipeline Design")[-1] == "20%"
    assert _row(tables, "Deployment & MLOps Planning")[-1] == "15%"
    assert _row(tables, "Ethical, Regulatory, and Risk Considerations")[-1] == "15%"
    assert _row(tables, "Presentation, Clarity, and Referencing")[-1] == "10%"

    assert _row(tables, "High Distinction (HD)")[1] == "85 \u2013 100%"
    assert _row(tables, "Fail (F)")[1].startswith("0 \u2013 49%")
    assert "Template note:" in _all_text(data)
    assert "Academic Grievance Policy" in _all_text(data)
    assert "Teaching and Assessment: Subject Delivery Policy" in _all_text(data)
    assert "LATE SUBMISSIONS" in _all_text(data)
    assert "Appendix - Policies" not in paragraphs


def test_blank_outline_has_no_demo_content() -> None:
    data = render_docx(empty_outline())
    paragraphs, tables = _docx(data)
    assert "SUBJECT NAME" in [row[0] for table in tables for row in table if row]
    assert "MAAI 903" not in _all_text(data)
    assert "Appendix - Policies" not in paragraphs
    assert "Marking Rubric" not in paragraphs


def test_pdf_contains_the_full_template_and_rubric() -> None:
    import fitz

    data = render_pdf(demo_outline())
    assert data[:4] == b"%PDF"

    document = fitz.open(stream=data, filetype="pdf")
    raw = "\n".join(page.get_text() for page in document)
    text = " ".join(raw.split())

    for heading in (
        "1. SUBJECT DESCRIPTION",
        "2. Learning Outcome and Contribution to Program learning outcomes (PLO)",
        "3. SUBJECT SCHEDULE",
        "4. SUPPORTING MATERIALS",
        "4.1 ACCESS TO SUPPORTING MATERIALS",
        "5. ASSESSMENT",
        "5.1 ASSESSMENT OF LEARNING OUTCOMES",
        "5.2 ASSESSMENT TASKS",
        "5.3 USING GENERATIVE AI (GENAI)",
        "5.4 GRADES AWARDED",
        "5.5 SATISFACTORY COMPLETION REQUIREMENTS",
        "6. RELEVANT POLICIES AND DOCUMENTS",
        "7. SSP & STUDIOSITY",
        "8. ACADEMIC INTEGRITY",
        "8.1 TURNITIN",
        "8.2 REFERENCE & IN-TEXT CITATION",
        "8.3 UOWD RULES & POLICIES",
        "9. ATTENDANCE REQUIREMENTS",
        "10. SUPPLEMENTARY ASSESSMENTS",
        "11. Lecture Capture",
        "12. Sustainability",
    ):
        assert heading in text, heading

    assert "Assessment 1 Workshops 25%" in text
    assert "Criteria" in text
    assert "Excellent (85-100%)" in text
    assert "Problem Definition & Business Context" in text
    assert "measurable business impact" in text
    assert "LATE SUBMISSIONS" in text
    assert "Academic Grievance Policy" in text
    assert "Teaching and Assessment: Subject Delivery Policy" in text
    assert "Template note:" in text
    assert "Appendix - Policies" not in text


class _FakeScalars:
    def all(self) -> list:
        return []

    def __iter__(self):
        return iter([])


class _FakeResult:
    def scalars(self) -> _FakeScalars:
        return _FakeScalars()

    def scalar_one_or_none(self) -> None:
        return None

    def scalar_one(self) -> int:
        return 0


class _FakeDB:
    def __init__(self, row) -> None:
        self.row = row
        self.added: list = []

    async def get(self, model, ident):
        return self.row if ident == self.row.id else None

    async def execute(self, *args, **kwargs):
        return _FakeResult()

    def add(self, item) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


def _row_fixture(body: dict):
    from app.profassist.models import SubjectOutline

    return SubjectOutline(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        code="NEW-TEST01",
        name="New subject",
        body=body,
        status="draft",
        pdf_key="",
        docx_key="",
        instructions="",
    )


def test_save_step_round_trips_every_body_array() -> None:
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    row.body["assessment_tasks"] = [
        {
            "number": "A1",
            "title": "Workshop",
            "type": "Individual",
            "weight": 100,
            "total_marks": 100,
            "due": "Week 1",
            "lo_codes": ["LO1"],
            "overview": ["Do the workshop."],
            "deliverables": ["Code"],
            "format": [],
            "rubric": [
                {
                    "name": "Quality",
                    "weight": 100,
                    "levels": {
                        "beginning": "Thin",
                        "developing": "Basic",
                        "proficient": "Good",
                        "advanced": "Excellent",
                    },
                }
            ],
        }
    ]
    db: Any = _FakeDB(row)
    org_id, user_id = row.organization_id, row.owner_user_id

    async def save(step: str, payload: dict) -> None:
        await save_step(db, org_id, user_id, row.id, step, payload, trust_course_text=True)

    async def run() -> dict:
        await save(
            "basics",
            {
                "name": "Flows 101",
                "code": "FLW101",
                "section": "A",
                "credit_points": "6",
                "year": "2026",
                "session": "Autumn",
                "duration": "11 weeks",
                "prerequisites": "None",
                "equivalent_subjects": "Nil",
                "delivery_mode": "F2F",
            },
        )
        await save(
            "lecture",
            {
                "day": "Monday",
                "time": "09:00-11:00",
                "location": "Room 1",
                "educator_name": "",
                "office": "Level 2",
                "email": "",
                "consultation": "Tuesday",
            },
        )
        await save("description", {"description": "A course about flows."})
        await save(
            "outcomes",
            {
                "program": "Master of Flows",
                "plos": [{"code": "PLO1", "text": "Apply flows."}],
                "clos": [{"code": "LO1", "text": "Explain flows.", "plos": ["PLO1"]}],
            },
        )
        await save(
            "schedule",
            {
                "weeks": [
                    {
                        "week": 1,
                        "topic": "Flows",
                        "lo_codes": ["LO1"],
                        "session_type": "Lecture",
                        "delivery": "F2F",
                        "assessment_note": "Workshop (F)",
                    }
                ]
            },
        )
        await save("readings", {"readings": ["Reading one."]})
        await save(
            "assessment_map",
            {"outcome_measures": [{"lo_code": "LO1", "measures": "A1 Workshop"}]},
        )
        await save("genai", {"genai": ["Verify outputs."]})
        await save(
            "grades",
            {
                "grades": [
                    {
                        "band": "High Distinction (HD)",
                        "range": "85-100%",
                        "description": "",
                    }
                ]
            },
        )
        await save(
            "satisfactory",
            {"satisfactory": ["Complete every task."], "satisfactory_note": "Check the exam."},
        )
        await save(
            "policy_documents",
            {"policy_documents": [{"title": "Academic Grievance Policy", "url": ""}]},
        )
        await save(
            "policies",
            {"policies": ["Legacy appendix policy"]},
        )
        await save("ssp", {"ssp": "Support is available."})
        await save(
            "academic_integrity",
            {"academic_integrity": {"intro": "Be honest.", "turnitin": "Submit online."}},
        )
        await save("attendance", {"attendance": "Come to class."})
        await save("supplementary", {"supplementary": "A supplementary may be offered."})
        await save("lecture_capture", {"lecture_capture": "Lectures are recorded."})
        await save("sustainability", {"sustainability": "Avoid printing."})
        await save("late_submission", {"late_submission": "20% per day."})
        return row.body

    body = asyncio.run(run())
    assert row.code == "FLW101"
    assert body["basics"]["name"] == "Flows 101"
    assert body["lecture"]["day"] == "Monday"
    assert body["description"] == "A course about flows."
    assert body["plos"] == [{"code": "PLO1", "text": "Apply flows."}]
    assert body["clos"][0]["plos"] == ["PLO1"]
    assert body["weeks"][0]["lo_codes"] == ["LO1"]
    assert body["readings"] == ["Reading one."]
    assert body["outcome_measures"] == [{"lo_code": "LO1", "measures": "A1 Workshop"}]
    assert body["assessment_tasks"][0]["rubric"][0]["weight"] == 100
    assert body["genai"] == ["Verify outputs."]
    assert body["grades"][0]["band"] == "High Distinction (HD)"
    assert body["satisfactory"] == ["Complete every task."]
    assert body["policy_documents"] == [{"title": "Academic Grievance Policy", "url": ""}]
    assert body["policies"] == ["Legacy appendix policy"]
    assert body["ssp"] == "Support is available."
    assert body["academic_integrity"]["intro"] == "Be honest."
    assert body["attendance"] == "Come to class."
    assert body["supplementary"] == "A supplementary may be offered."
    assert body["lecture_capture"] == "Lectures are recorded."
    assert body["sustainability"] == "Avoid printing."
    assert body["late_submission"] == "20% per day."
    assert "tasks" not in body


def test_save_step_trusts_the_course_text_by_default() -> None:
    """Demo course content is not a student submission: names and authors save."""
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)
    demo = demo_outline()
    org_id, user_id = row.organization_id, row.owner_user_id

    async def save(step: str, payload: dict) -> None:
        await save_step(db, org_id, user_id, row.id, step, payload)

    async def run() -> None:
        await save("basics", demo["basics"])
        await save("lecture", demo["lecture"])
        await save("description", {"description": demo["description"]})
        await save(
            "outcomes",
            {"program": demo["program"], "plos": demo["plos"], "clos": demo["clos"]},
        )
        await save("schedule", {"weeks": demo["weeks"]})
        await save("readings", {"readings": demo["readings"]})
        await save("assessment_map", {"outcome_measures": demo["outcome_measures"]})
        await save("policies", {"policies": demo["policy_documents"]})

    asyncio.run(run())

    assert row.code == "MAAI 903"
    assert row.body["basics"]["name"] == "AI Solutions Design & MLOps"
    # The lecture is public staff information, so the educator contact stays.
    assert row.body["lecture"]["educator_name"] == "Dr Patrick Mukala"
    assert row.body["lecture"]["email"] == "PATRICKMUKALA@UOWDUBAI.AC.AE"
    assert row.body["lecture"]["office"] == "3rd Floor in the New building"
    assert row.body["lecture"]["consultation"] == demo["lecture"]["consultation"]
    assert row.body["description"] == demo["description"]
    assert row.body["weeks"] == demo["weeks"]
    assert row.body["readings"] == demo["readings"]
    assert row.body["outcome_measures"] == demo["outcome_measures"]
    assert row.body["policies"] == demo["policy_documents"]


def test_save_step_keeps_an_en_dash_range_in_the_grades() -> None:
    """A JSON escape is not a phone number: an en dash range must persist."""
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)
    grades = [
        {"band": "High Distinction", "range": "85 \u2013 100%", "grade": "HD"},
        {"band": "Distinction", "range": "75 \u2013 84%", "grade": "D"},
    ]

    asyncio.run(
        save_step(
            db,
            row.organization_id,
            row.owner_user_id,
            row.id,
            "grades",
            {"grades": grades},
        )
    )

    assert row.body["grades"] == grades


def test_save_step_route_saves_an_en_dash_grades_step() -> None:
    """The PUT /outlines/{id}/step path the E2E exercise hit returned a 500."""
    from types import SimpleNamespace

    from app.api.routes.v1.profassist import StepBody, outlines_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)
    payload = {"grades": [{"band": "High Distinction", "range": "85 \u2013 100%"}]}

    result = asyncio.run(
        outlines_step(
            row.id,
            StepBody(step="grades", payload=payload),
            SimpleNamespace(id=row.owner_user_id),
            SimpleNamespace(id=row.organization_id),
            db,
        )
    )

    assert result["body"]["grades"] == payload["grades"]


def test_save_step_still_scrubs_a_contact_in_a_string_leaf() -> None:
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)

    asyncio.run(
        save_step(
            db,
            row.organization_id,
            row.owner_user_id,
            row.id,
            "grades",
            {"grades": [{"band": "Email jane@example.edu or call 0432 123 456"}]},
        )
    )

    saved = row.body["grades"][0]["band"]
    assert "jane@example.edu" not in saved
    assert "0432 123 456" not in saved


def test_save_step_strict_gate_still_quarantines_student_pii() -> None:
    from app.profassist.errors import ProfassistError
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)
    payload = {"weeks": [{"week": 1, "topic": "Alice Johnson 12345678"}]}

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            save_step(
                db,
                row.organization_id,
                row.owner_user_id,
                row.id,
                "schedule",
                payload,
                trust_course_text=False,
            )
        )

    assert caught.value.status == 400
    assert "student" in caught.value.detail.lower()


class _DuplicateCodeDB(_FakeDB):
    def __init__(self, row, taken: set[str]) -> None:
        super().__init__(row)
        self.taken = taken
        self.rolled_back = False

    async def flush(self) -> None:
        if self.row.code in self.taken:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError(
                "UPDATE pa_subject_outlines", {}, Exception("uq_pa_outline_owner_code")
            )
        return None

    async def rollback(self) -> None:
        self.rolled_back = True


def test_duplicate_outline_code_is_a_409_not_a_500() -> None:
    from app.profassist.errors import ProfassistError
    from app.profassist.outline import save_step

    first = _row_fixture(empty_outline())
    first.code = "MAAI 903"
    second = _row_fixture(empty_outline())
    db: Any = _DuplicateCodeDB(second, taken={first.code})

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            save_step(
                db,
                second.organization_id,
                second.owner_user_id,
                second.id,
                "basics",
                {"code": "MAAI 903", "name": "Second outline"},
            )
        )

    assert caught.value.status == 409
    assert "already exists" in caught.value.detail
    assert db.rolled_back is True


def test_finish_outline_writes_documents_without_assessment_rows(monkeypatch) -> None:
    import app.profassist.outline as outline
    from app.profassist.models import Assessment, OutlineTask, RubricCriterion

    row = _row_fixture(demo_outline())
    db: Any = _FakeDB(row)
    course = SimpleNamespace(id=uuid.uuid4(), clos=[])

    async def fake_course_for(db_session, org_id, body):
        return course

    monkeypatch.setattr(outline, "_course_for", fake_course_for)
    monkeypatch.setattr(outline, "render_pdf", lambda body: b"%PDF-1.4")
    monkeypatch.setattr(outline, "render_docx", lambda body: b"PK\x03\x04")
    monkeypatch.setattr(outline, "save_bytes", lambda key, data, content_type: key)
    monkeypatch.setattr(outline, "index_outline", lambda *args, **kwargs: None)

    result = asyncio.run(outline.finish_outline(db, row.organization_id, row.owner_user_id, row.id))

    assert result["status"] == "published"
    assert result["pdf_ready"] is True
    assert result["docx_ready"] is True
    assert "tasks" not in row.body
    assert len(row.body["assessment_tasks"]) == 4
    assert row.body["outcome_measures"] == demo_outline()["outcome_measures"]
    assert not any(
        isinstance(item, (Assessment, OutlineTask, RubricCriterion)) for item in db.added
    )
    added = {type(item).__name__ for item in db.added}
    assert {"ProgramOutcome", "CourseOutcome", "OutlineWeek", "OutlineReading"} <= added
    assert "OutlinePolicy" not in added


class _ListScalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items

    def __iter__(self):
        return iter(self.items)


class _ListResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return _ListScalars(self.items)


class _QueueDB:
    def __init__(self, results, rows=None):
        self.results = list(results)
        self.rows = rows or {}

    async def execute(self, *args, **kwargs):
        return self.results.pop(0)

    async def get(self, model, ident):
        return (self.rows.get(model) or {}).get(ident)


def test_finish_snapshot_prefers_linked_assignments_and_rubric() -> None:
    from app.profassist.models import Assessment
    from app.profassist.outline import _with_assessment_tasks

    aid = uuid.uuid4()
    course: Any = SimpleNamespace(id=uuid.uuid4())
    group = SimpleNamespace(
        id=uuid.uuid4(),
        number="A2",
        title="Linked Assignment",
        weight=30,
        due="Week 8",
        lo_codes=["LO2"],
        body="Group brief",
        assessment_id=aid,
        outline_task_id=None,
    )
    assessment = SimpleNamespace(
        id=aid,
        title="Linked Assignment",
        brief="Individual brief",
        clos=["LO2"],
        weight=30,
        kind="assignment",
        external_id="outline:A2",
    )
    criterion = SimpleNamespace(
        name="Evidence",
        weight=40,
        levels={"advanced": "Strong evidence"},
        ordinal=1,
    )
    db: Any = _QueueDB(
        [
            _ListResult([group]),
            _ListResult([criterion]),
            _ListResult([]),
        ],
        {Assessment: {aid: assessment}},
    )
    snapshot = {
        "assessment_tasks": [
            {"number": "A1", "title": "Snapshot task", "rubric": [], "lo_codes": []}
        ]
    }
    result = asyncio.run(_with_assessment_tasks(db, uuid.uuid4(), uuid.uuid4(), course, snapshot))
    tasks = result["assessment_tasks"]
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Linked Assignment"
    assert tasks[0]["type"] == "Group"
    assert tasks[0]["weight"] == 30
    assert tasks[0]["due"] == "Week 8"
    assert tasks[0]["rubric"] == [
        {"name": "Evidence", "weight": 40, "levels": {"advanced": "Strong evidence"}}
    ]
    assert tasks[0]["entity_id"] == str(group.id)


def test_finish_keeps_snapshot_when_no_assignments_exist() -> None:
    from app.profassist.outline import _with_assessment_tasks

    snapshot = {
        "assessment_tasks": [
            {
                "number": "A1",
                "title": "Snapshot task",
                "type": "Individual",
                "weight": 25,
                "total_marks": 100,
                "due": "Week 7",
                "lo_codes": ["LO1"],
                "overview": ["A snapshot brief."],
                "deliverables": ["Report"],
                "format": ["APA 7"],
                "rubric": [{"name": "Evidence", "weight": 100, "levels": {}}],
            }
        ]
    }
    db: Any = _QueueDB([_ListResult([]), _ListResult([])])
    course: Any = SimpleNamespace(id=uuid.uuid4())
    result = asyncio.run(_with_assessment_tasks(db, uuid.uuid4(), uuid.uuid4(), course, snapshot))
    assert result["assessment_tasks"] == snapshot["assessment_tasks"]


def test_empty_rubric_does_not_invent_criteria() -> None:
    from app.profassist.outline_doc import _rubric_rows

    assert _rubric_rows({"rubric": []}) == []


def test_no_assessment_tasks_renders_an_honest_line() -> None:
    body = empty_outline()
    body["basics"]["name"] = "Blank subject"
    body["assessment_tasks"] = []
    docx_text = _all_text(render_docx(body))
    assert "No assessment tasks yet." in docx_text

    import fitz

    document = fitz.open(stream=render_pdf(body), filetype="pdf")
    pdf_text = " ".join("\n".join(page.get_text() for page in document).split())
    assert "No assessment tasks yet." in pdf_text


def test_assessment_tasks_cannot_be_saved_from_the_outline() -> None:
    from app.profassist.errors import ProfassistError
    from app.profassist.outline import save_step

    row = _row_fixture(empty_outline())
    db: Any = _FakeDB(row)
    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            save_step(
                db,
                row.organization_id,
                row.owner_user_id,
                row.id,
                "assessment_tasks",
                {"assessment_tasks": [{"number": "A1"}]},
            )
        )
    assert caught.value.status == 400
