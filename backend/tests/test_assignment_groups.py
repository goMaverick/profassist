"""Assignment-scoped groups: save, scope, roster checks, and the chat tool.

The session below is a small in-memory stand-in for AsyncSession so the real
service functions and routes run without a database.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import DateTime, Delete
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, Null

from app.core.config import settings
from app.profassist.errors import ProfassistError
from app.profassist.groupwork import assignment_groups, assignment_view, save_groups
from app.profassist.models import Course, GroupAssignment, Student, StudentGroup


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self.first()


def _criteria(statement) -> list[tuple[str, object, str]]:
    filters: list[tuple[str, object, str]] = []
    for criterion in getattr(statement, "_where_criteria", ()):
        key = getattr(getattr(criterion, "left", None), "key", None)
        if not key:
            continue
        right = getattr(criterion, "right", None)
        if isinstance(right, Null):
            filters.append((key, None, "is"))
        elif isinstance(right, BindParameter):
            kind = "in" if getattr(criterion, "operator", None) is operators.in_op else "eq"
            filters.append((key, right.value, kind))
    return filters


def _matches(row: object, filters: list[tuple[str, object, str]]) -> bool:
    for key, value, kind in filters:
        actual = getattr(row, key, object())
        if kind == "is":
            if actual is not None:
                return False
        elif kind == "in":
            if actual not in value:
                return False
        elif actual != value:
            return False
    return True


def _apply_defaults(row: object) -> None:
    for attr in sa_inspect(type(row)).mapper.column_attrs:
        if getattr(row, attr.key, None) is not None:
            continue
        column = attr.columns[0]
        if column.default is not None:
            try:
                value = column.default.arg(None)
            except TypeError:
                value = column.default.arg
        elif column.server_default is not None and isinstance(column.type, DateTime):
            from datetime import UTC, datetime

            value = datetime.now(UTC)
        else:
            continue
        setattr(row, attr.key, value)


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            _apply_defaults(row)

    async def get(self, model, ident):
        for row in self.rows:
            if isinstance(row, model) and getattr(row, "id", None) == ident:
                return row
        return None

    async def execute(self, statement):
        if isinstance(statement, Delete):
            table = statement.table.name
            filters = _criteria(statement)
            self.rows = [
                row
                for row in self.rows
                if not (getattr(row, "__tablename__", "") == table and _matches(row, filters))
            ]
            return _Result([])
        entity = statement.column_descriptions[0]["entity"]
        filters = _criteria(statement)
        rows = [row for row in self.rows if isinstance(row, entity) and _matches(row, filters)]
        return _Result(rows)


async def _workspace():
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(
        organization_id=org_id, code="AAS 910", title="Assurance Studio", term="2026", clos=[]
    )
    other_course = Course(
        organization_id=org_id, code="AAS 911", title="Another course", term="2026", clos=[]
    )
    db.add(course)
    db.add(other_course)
    await db.flush()

    students = []
    for index in range(1, 7):
        student = Student(
            organization_id=org_id,
            course_id=course.id,
            external_id=f"s{index}",
            display_name=f"Student {index}",
        )
        db.add(student)
        students.append(student)
    outsider = Student(
        organization_id=org_id,
        course_id=other_course.id,
        external_id="o1",
        display_name="Outsider",
    )
    db.add(outsider)
    await db.flush()

    assignment_a = GroupAssignment(
        organization_id=org_id, owner_user_id=user_id, course_id=course.id, number="1", title="A"
    )
    assignment_b = GroupAssignment(
        organization_id=org_id, owner_user_id=user_id, course_id=course.id, number="2", title="B"
    )
    db.add(assignment_a)
    db.add(assignment_b)
    foreign = GroupAssignment(
        organization_id=uuid.uuid4(),
        owner_user_id=user_id,
        course_id=course.id,
        number="9",
        title="Foreign",
    )
    db.add(foreign)
    await db.flush()

    return SimpleNamespace(
        db=db,
        org_id=org_id,
        user_id=user_id,
        course=course,
        other_course=other_course,
        students=students,
        outsider=outsider,
        assignment_a=assignment_a,
        assignment_b=assignment_b,
        foreign=foreign,
    )


@pytest.mark.anyio
async def test_groups_are_scoped_to_their_assignment() -> None:
    w = await _workspace()
    await save_groups(
        w.db,
        w.org_id,
        w.user_id,
        w.course.id,
        [{"name": "Course group", "member_ids": [str(w.students[0].id)]}],
    )
    saved = await save_groups(
        w.db,
        w.org_id,
        w.user_id,
        w.course.id,
        [{"name": "A group", "member_ids": [str(w.students[1].id)]}],
        assignment_id=w.assignment_a.id,
    )

    assert [item["name"] for item in saved] == ["A group"]

    view_a = await assignment_view(w.db, w.org_id, w.user_id, w.assignment_a.id)
    view_b = await assignment_view(w.db, w.org_id, w.user_id, w.assignment_b.id)
    assert [group["name"] for group in view_a["groups"]] == ["A group"]
    assert view_b["groups"] == []

    listed = await assignment_groups(w.db, w.org_id, w.user_id, w.assignment_a.id)
    assert [group["name"] for group in listed] == ["A group"]

    # The course-level group was not replaced by the assignment save.
    course_level = [
        row for row in w.db.rows if isinstance(row, StudentGroup) and row.assignment_id is None
    ]
    assert [row.name for row in course_level] == ["Course group"]


@pytest.mark.anyio
async def test_saving_course_groups_leaves_assignment_groups_alone() -> None:
    w = await _workspace()
    await save_groups(
        w.db,
        w.org_id,
        w.user_id,
        w.course.id,
        [{"name": "A group", "member_ids": []}],
        assignment_id=w.assignment_a.id,
    )
    await save_groups(
        w.db,
        w.org_id,
        w.user_id,
        w.course.id,
        [{"name": "Fresh course group", "member_ids": []}],
    )

    view_a = await assignment_view(w.db, w.org_id, w.user_id, w.assignment_a.id)
    assert [group["name"] for group in view_a["groups"]] == ["A group"]


@pytest.mark.anyio
async def test_foreign_assignment_is_hidden_with_404() -> None:
    w = await _workspace()

    with pytest.raises(ProfassistError) as caught:
        await assignment_groups(w.db, w.org_id, w.user_id, w.foreign.id)
    assert caught.value.status == 404

    with pytest.raises(ProfassistError) as save_error:
        await save_groups(
            w.db,
            w.org_id,
            w.user_id,
            w.course.id,
            [{"name": "Sneaky", "member_ids": []}],
            assignment_id=w.foreign.id,
        )
    assert save_error.value.status == 404


@pytest.mark.anyio
async def test_allocate_only_allocates_to_assignment_groups() -> None:
    from app.profassist.groupwork import allocate, save_ideas

    w = await _workspace()
    await save_groups(
        w.db,
        w.org_id,
        w.user_id,
        w.course.id,
        [{"name": "A group", "member_ids": []}],
        assignment_id=w.assignment_a.id,
    )
    await save_ideas(
        w.db,
        w.org_id,
        w.user_id,
        w.assignment_a.id,
        [{"title": "Idea", "brief": "Brief", "deliverables": "", "evidence": ""}],
    )

    view_a = await allocate(w.db, w.org_id, w.user_id, w.assignment_a.id)
    view_b = await assignment_view(w.db, w.org_id, w.user_id, w.assignment_b.id)

    assert len(view_a["allocations"]) == 1
    assert view_a["allocations"][0]["group_id"] == view_a["groups"][0]["id"]
    assert view_b["allocations"] == []


def _override_dependencies(w) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    user = MagicMock()
    user.id = w.user_id
    user.has_role.return_value = True
    app.dependency_overrides[get_db_session] = lambda: w.db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=w.org_id)


@pytest.mark.anyio
async def test_route_rejects_a_member_from_another_course(client, mock_db_session) -> None:
    w = await _workspace()
    _override_dependencies(w)

    response = await client.post(
        f"{settings.API_V1_STR}/profassist/assignments/{w.assignment_a.id}/groups",
        json={"groups": [{"name": "Bad", "member_ids": [str(w.outsider.id)]}]},
    )

    assert response.status_code == 400, response.text
    assert "roster" in response.json()["detail"]
    assert await assignment_groups(w.db, w.org_id, w.user_id, w.assignment_a.id) == []


@pytest.mark.anyio
async def test_route_saves_and_lists_assignment_groups(client, mock_db_session) -> None:
    w = await _workspace()
    _override_dependencies(w)
    member_ids = [str(w.students[0].id), str(w.students[1].id)]

    saved = await client.post(
        f"{settings.API_V1_STR}/profassist/assignments/{w.assignment_a.id}/groups",
        json={"groups": [{"name": "A group", "member_ids": member_ids}]},
    )
    assert saved.status_code == 200, saved.text
    assert [item["name"] for item in saved.json()["items"]] == ["A group"]

    listed = await client.get(
        f"{settings.API_V1_STR}/profassist/assignments/{w.assignment_a.id}/groups"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["member_ids"] == member_ids


@pytest.mark.anyio
async def test_route_hides_a_foreign_assignment(client, mock_db_session) -> None:
    w = await _workspace()
    _override_dependencies(w)

    response = await client.get(
        f"{settings.API_V1_STR}/profassist/assignments/{w.foreign.id}/groups"
    )

    assert response.status_code == 404, response.text


@pytest.mark.anyio
async def test_create_groups_tool_splits_the_roster_for_an_assignment() -> None:
    from app.profassist.platform_tools import clear_tool_actor, invoke_tool, set_tool_actor

    w = await _workspace()
    set_tool_actor(w.org_id, w.user_id, is_admin=False)
    try:
        waiting = await invoke_tool(
            w.db,
            "create_groups",
            {
                "course_id": str(w.course.id),
                "assignment_id": str(w.assignment_a.id),
                "group_count": 2,
            },
            confirmed=False,
        )
        assert waiting["needs_confirm"] is True
        assert await assignment_groups(w.db, w.org_id, w.user_id, w.assignment_a.id) == []

        payload = await invoke_tool(
            w.db,
            "create_groups",
            {
                "course_id": str(w.course.id),
                "assignment_id": str(w.assignment_a.id),
                "group_count": 2,
            },
            confirmed=True,
        )
    finally:
        clear_tool_actor()

    assert payload["needs_confirm"] is False
    assert payload["result"]["assignment_id"] == str(w.assignment_a.id)
    assert [item["name"] for item in payload["result"]["groups"]] == ["Group 1", "Group 2"]

    persisted = await assignment_groups(w.db, w.org_id, w.user_id, w.assignment_a.id)
    assert [len(item["member_ids"]) for item in persisted] == [3, 3]
    assert persisted[0]["member_ids"] == [str(student.id) for student in w.students[:3]]
    assert persisted[1]["member_ids"] == [str(student.id) for student in w.students[3:]]
