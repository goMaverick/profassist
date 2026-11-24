"""Rubric flow: blank create, draft, save, import, check, approve, and the owner lock.

The session below is a small in-memory stand-in for AsyncSession so the real
service functions run without a database.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import DateTime, Delete
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter

from app.core.config import settings
from app.profassist import service
from app.profassist.errors import ProfassistError
from app.profassist.models import Course

PASTED = """Criterion: Evidence
Weight: 2
Beginning: Names the task
Developing: Partly shows it
Proficient: Quotes an example
Advanced: States a limitation

Criterion: Style
Weight: 1
Beginning: A start
Developing: Clear in places
Proficient: Reads cleanly
Advanced: Precise throughout
"""


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


def _where(statement) -> dict[str, object]:
    filters: dict[str, object] = {}
    for criterion in getattr(statement, "_where_criteria", ()):
        key = getattr(getattr(criterion, "left", None), "key", None)
        right = getattr(criterion, "right", None)
        if key and isinstance(right, BindParameter):
            filters[key] = right.value
    return filters


def _matches(row: object, filters: dict[str, object]) -> bool:
    return all(getattr(row, key, object()) == value for key, value in filters.items())


def _sort_key(value: object) -> tuple[int, object]:
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, datetime):
        return (0, value.timestamp())
    return (0, str(value))


def _ordered(rows: list[object], statement) -> list[object]:
    for clause in reversed(getattr(statement, "_order_by_clauses", ())):
        key = getattr(clause, "key", None)
        descending = False
        if key is None and hasattr(clause, "element"):
            # ``column.desc()`` / ``column.asc()`` wrap the column in a unary expression.
            key = getattr(clause.element, "key", None)
            descending = getattr(clause, "modifier", None) is operators.desc_op
        if not key:
            continue
        rows = sorted(
            rows,
            key=lambda row, name=key: _sort_key(getattr(row, name, None)),
            reverse=descending,
        )
    return rows


def _apply_defaults(row: object, now) -> None:
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
            value = now()
        else:
            continue
        setattr(row, attr.key, value)


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[object] = []
        # Postgres ``now()`` is transaction time. Advance a private clock for
        # every defaulted insert so separate flushes never share a microsecond;
        # otherwise created_at ties fall back to random UUID order.
        self._clock = datetime.now(UTC)

    def _next_timestamp(self) -> datetime:
        self._clock += timedelta(microseconds=1)
        return self._clock

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            _apply_defaults(row, self._next_timestamp)

    async def get(self, model, ident):
        for row in self.rows:
            if isinstance(row, model) and getattr(row, "id", None) == ident:
                return row
        return None

    async def execute(self, statement):
        if isinstance(statement, Delete):
            table = statement.table.name
            filters = _where(statement)
            self.rows = [
                row
                for row in self.rows
                if not (getattr(row, "__tablename__", "") == table and _matches(row, filters))
            ]
            return _Result([])
        entity = statement.column_descriptions[0]["entity"]
        filters = _where(statement)
        rows = [row for row in self.rows if isinstance(row, entity) and _matches(row, filters)]
        return _Result(_ordered(rows, statement))


CLOS = ["Explain how an LLM agent differs from a trained machine learning model."]


async def _workspace(clos: list[str] | None = None):
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(
        organization_id=org_id,
        code="AAS 910",
        title="Assurance Studio",
        term="2026",
        clos=CLOS if clos is None else clos,
    )
    db.add(course)
    await db.flush()
    return db, org_id, user_id, course


def _criteria() -> list[dict]:
    return [
        {
            "name": "Evidence",
            "weight": 40,
            "levels": {
                "beginning": "Names the task",
                "developing": "Explains the agent",
                "proficient": "Explains how an LLM agent differs from a model",
                "advanced": "States a limitation",
            },
        },
        {
            "name": "Design",
            "weight": 60,
            "levels": {
                "beginning": "A sketch",
                "developing": "Some detail",
                "proficient": "Design is explained",
                "advanced": "Design is defended",
            },
        },
    ]


@pytest.mark.anyio
async def test_blank_rubric_starts_empty_and_lists_its_criteria() -> None:
    db, org_id, user_id, course = await _workspace()

    created = await service.create_rubric(db, org_id, course.id, user_id, "Blank rubric")

    assert created["status"] == "draft"
    assert created["version"] == 1
    assert created["criteria"] == []

    saved = await service.save_rubric(
        db, org_id, user_id, uuid.UUID(created["id"]), _criteria(), "Groups report on agents."
    )
    assert saved["brief"] == "Groups report on agents."
    assert [item["name"] for item in saved["criteria"]] == ["Evidence", "Design"]
    assert [item["weight"] for item in saved["criteria"]] == [40, 60]
    assert saved["criteria"][0]["levels"]["proficient"].startswith("Explains how")

    listed = await service.list_assessments(db, org_id, course.id, user_id)
    assert len(listed) == 1
    # The list payload carries the criteria, not only the detail payload.
    assert [item["name"] for item in listed[0]["criteria"]] == ["Evidence", "Design"]
    assert listed[0]["status"] == "draft"


@pytest.mark.anyio
async def test_saving_again_bumps_the_version_and_keeps_history() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Versioned")
    first = await service.save_rubric(db, org_id, user_id, uuid.UUID(created["id"]), _criteria())
    assert first["version"] == 1
    assert first["history_count"] == 0

    second = await service.save_rubric(db, org_id, user_id, uuid.UUID(created["id"]), _criteria())
    assert second["version"] == 2
    assert second["history_count"] == 1
    assert second["status"] == "draft"


@pytest.mark.anyio
async def test_approve_refuses_an_empty_rubric() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Empty")

    with pytest.raises(ProfassistError) as caught:
        await service.approve_assessment(db, org_id, user_id, uuid.UUID(created["id"]))

    assert caught.value.status == 400
    assert "Design the rubric" in caught.value.detail
    still = await service.list_assessments(db, org_id, course.id, user_id)
    assert still[0]["status"] == "draft"


@pytest.mark.anyio
async def test_approve_refuses_a_rubric_with_no_level_text() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Shell")
    await service.save_rubric(
        db,
        org_id,
        user_id,
        uuid.UUID(created["id"]),
        [{"name": "Evidence", "weight": 100, "levels": {"beginning": "", "advanced": "  "}}],
    )

    with pytest.raises(ProfassistError) as caught:
        await service.approve_assessment(db, org_id, user_id, uuid.UUID(created["id"]))
    assert caught.value.status == 400
    assert "Describe at least one level" in caught.value.detail


@pytest.mark.anyio
async def test_approved_rubric_cannot_be_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "reflect_on_change", AsyncMock())
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Locked")
    assessment_id = uuid.UUID(created["id"])
    await service.save_rubric(db, org_id, user_id, assessment_id, _criteria())

    approved = await service.approve_assessment(db, org_id, user_id, assessment_id)
    assert approved["status"] == "approved"

    with pytest.raises(ProfassistError) as save_error:
        await service.save_rubric(db, org_id, user_id, assessment_id, _criteria()[:1])
    assert save_error.value.status == 409

    with pytest.raises(ProfassistError) as import_error:
        await service.import_rubric(db, org_id, user_id, assessment_id, "", b"", PASTED)
    assert import_error.value.status == 409

    with pytest.raises(ProfassistError) as draft_error:
        await service.draft_assessment(db, org_id, course.id, user_id)
    assert draft_error.value.status == 409

    after = await service.get_assessment(db, org_id, course.id, user_id)
    assert after is not None
    assert after["status"] == "approved"
    assert [item["name"] for item in after["criteria"]] == ["Evidence", "Design"]


@pytest.mark.anyio
async def test_approve_twice_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    reflect = AsyncMock()
    monkeypatch.setattr(service, "reflect_on_change", reflect)
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Twice")
    assessment_id = uuid.UUID(created["id"])
    await service.save_rubric(db, org_id, user_id, assessment_id, _criteria())

    await service.approve_assessment(db, org_id, user_id, assessment_id)
    again = await service.approve_assessment(db, org_id, user_id, assessment_id)

    assert again["status"] == "approved"
    assert reflect.await_count == 1
    audits = [row for row in db.rows if getattr(row, "target_type", "") == "assessment"]
    assert len(audits) == 1


def _fake_rubric_model(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub everything around the model so drafting only exercises the rubric branch."""
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "recall", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        service,
        "_chunks",
        AsyncMock(return_value=[SimpleNamespace(id=uuid.uuid4(), text="Lecture note")]),
    )
    monkeypatch.setattr(service, "_soul", AsyncMock(return_value=""))
    run_course = MagicMock(
        return_value={
            "brief": "Drafted brief",
            "criteria": [
                {
                    "name": "Drafted criterion",
                    "weight": 100,
                    "levels": {"beginning": "Starts", "proficient": "Explains the agent"},
                }
            ],
        }
    )
    monkeypatch.setattr(service.agents, "run_course", run_course)
    return run_course


@pytest.mark.anyio
async def test_draft_targets_the_selected_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_course = _fake_rubric_model(monkeypatch)
    db, org_id, user_id, course = await _workspace()
    older = await service.create_rubric(db, org_id, course.id, user_id, "Older draft")
    newer = await service.create_rubric(db, org_id, course.id, user_id, "Newer draft")

    drafted = await service.draft_assessment(db, org_id, course.id, user_id, uuid.UUID(older["id"]))

    # The explicit target wins even though the default would pick the newest draft.
    assert drafted["id"] == older["id"]
    assert drafted["brief"] == "Drafted brief"
    assert [item["name"] for item in drafted["criteria"]] == ["Drafted criterion"]
    run_course.assert_called_once()

    by_id = {
        row["id"]: row for row in await service.list_assessments(db, org_id, course.id, user_id)
    }
    assert by_id[newer["id"]]["criteria"] == []
    assert by_id[newer["id"]]["status"] == "draft"

    # Without a target it still drafts the newest draft, and the older one is left alone.
    drafted_newest = await service.draft_assessment(db, org_id, course.id, user_id)
    assert drafted_newest["id"] == newer["id"]
    assert run_course.call_count == 2
    by_id = {
        row["id"]: row for row in await service.list_assessments(db, org_id, course.id, user_id)
    }
    assert [item["name"] for item in by_id[older["id"]]["criteria"]] == ["Drafted criterion"]


@pytest.mark.anyio
async def test_draft_refuses_an_approved_rubric_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_course = _fake_rubric_model(monkeypatch)
    monkeypatch.setattr(service, "reflect_on_change", AsyncMock())
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Approved one")
    assessment_id = uuid.UUID(created["id"])
    await service.save_rubric(db, org_id, user_id, assessment_id, _criteria())
    await service.approve_assessment(db, org_id, user_id, assessment_id)

    with pytest.raises(ProfassistError) as caught:
        await service.draft_assessment(db, org_id, course.id, user_id, assessment_id)

    assert caught.value.status == 409
    assert caught.value.detail == service.APPROVED_RUBRIC_LOCKED
    run_course.assert_not_called()
    after = await service.get_assessment(db, org_id, course.id, user_id)
    assert after is not None
    assert after["status"] == "approved"
    assert [item["name"] for item in after["criteria"]] == ["Evidence", "Design"]


@pytest.mark.anyio
async def test_draft_hides_a_rubric_from_another_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_course = _fake_rubric_model(monkeypatch)
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Mine")
    other_org = uuid.uuid4()
    other_course = Course(
        organization_id=other_org, code="OTHER 101", title="Other", term="2026", clos=[]
    )
    db.add(other_course)
    await db.flush()

    with pytest.raises(ProfassistError) as caught:
        await service.draft_assessment(
            db, other_org, other_course.id, user_id, uuid.UUID(created["id"])
        )

    assert caught.value.status == 404
    run_course.assert_not_called()


@pytest.mark.anyio
async def test_draft_refuses_a_rubric_from_another_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_course = _fake_rubric_model(monkeypatch)
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Mine")
    second_course = Course(
        organization_id=org_id, code="AAS 911", title="Second course", term="2026", clos=[]
    )
    db.add(second_course)
    await db.flush()

    with pytest.raises(ProfassistError) as caught:
        await service.draft_assessment(
            db, org_id, second_course.id, user_id, uuid.UUID(created["id"])
        )

    assert caught.value.status == 404
    run_course.assert_not_called()


@pytest.mark.anyio
async def test_import_parses_a_pasted_rubric_and_a_file() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Imported")
    assessment_id = uuid.UUID(created["id"])

    pasted = await service.import_rubric(db, org_id, user_id, assessment_id, "", b"", PASTED)
    assert [item["name"] for item in pasted["criteria"]] == ["Evidence", "Style"]
    assert pasted["criteria"][0]["weight"] == 2
    assert pasted["criteria"][0]["levels"]["advanced"] == "States a limitation"
    assert pasted["status"] == "draft"

    file_row = await service.import_rubric(
        db, org_id, user_id, assessment_id, "rubric.txt", PASTED.encode("utf-8")
    )
    assert [item["name"] for item in file_row["criteria"]] == ["Evidence", "Style"]
    assert file_row["version"] == pasted["version"] + 1


def test_parse_rubric_text_splits_criteria_without_blank_lines() -> None:
    from app.profassist.rubric_build import parse_rubric_text

    rows = parse_rubric_text(PASTED.replace("\n\n", "\n"))

    assert [row["name"] for row in rows] == ["Evidence", "Style"]
    assert rows[0]["weight"] == 2
    assert rows[0]["levels"]["advanced"] == "States a limitation"
    assert rows[1]["levels"]["proficient"] == "Reads cleanly"


@pytest.mark.anyio
async def test_import_refuses_text_without_criteria() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Nothing")
    with pytest.raises(ProfassistError) as caught:
        await service.import_rubric(db, org_id, user_id, uuid.UUID(created["id"]), "", b"", "hello")
    assert caught.value.status == 400
    assert "No criteria were found" in caught.value.detail


@pytest.mark.anyio
async def test_alignment_flags_are_returned_and_persisted() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Flags")
    assessment_id = uuid.UUID(created["id"])
    await service.save_rubric(
        db,
        org_id,
        user_id,
        assessment_id,
        [
            {
                "name": "Style",
                "weight": 100,
                "levels": {
                    "beginning": "A good try",
                    "developing": "Appropriate detail",
                    "proficient": "Various points",
                    "advanced": "Nice work",
                },
            }
        ],
    )

    checked = await service.check_rubric(db, org_id, user_id, assessment_id)
    flags = checked["alignment"]["flags"]
    assert any("vague wording" in flag for flag in flags)
    assert any("No criterion mentions this outcome" in flag for flag in flags)
    assert checked["alignment"]["clos"] == CLOS
    listed = await service.list_assessments(db, org_id, course.id, user_id)
    assert listed[0]["alignment"]["flags"] == flags


@pytest.mark.anyio
async def test_another_professor_cannot_mutate_the_rubric() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Mine")
    assessment_id = uuid.UUID(created["id"])
    other = uuid.uuid4()

    for call in (
        lambda: service.save_rubric(db, org_id, other, assessment_id, _criteria()),
        lambda: service.import_rubric(db, org_id, other, assessment_id, "", b"", PASTED),
        lambda: service.check_rubric(db, org_id, other, assessment_id),
        lambda: service.approve_assessment(db, org_id, other, assessment_id),
    ):
        with pytest.raises(ProfassistError) as caught:
            await call()
        assert caught.value.status == 404

    # A rubric from another tenant is hidden even from its own owner.
    with pytest.raises(ProfassistError) as caught:
        await service.save_rubric(db, uuid.uuid4(), user_id, assessment_id, _criteria())
    assert caught.value.status == 404


@pytest.mark.anyio
async def test_malformed_criteria_are_rejected_not_crashing() -> None:
    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Malformed")
    assessment_id = uuid.UUID(created["id"])

    with pytest.raises(ProfassistError) as caught:
        await service.save_rubric(db, org_id, user_id, assessment_id, ["not a criterion"])
    assert caught.value.status == 400

    saved = await service.save_rubric(
        db,
        org_id,
        user_id,
        assessment_id,
        [
            {"name": "Zero", "weight": 0, "levels": {"beginning": "x"}},
            {"name": "Text", "weight": "heavy", "levels": {"beginning": "y"}},
            {"name": "Odd", "weight": 12.9, "levels": "nope"},
        ],
    )
    assert [item["weight"] for item in saved["criteria"]] == [0, 1, 12]
    assert saved["criteria"][2]["levels"] == {}


@pytest.mark.anyio
async def test_draft_route_passes_the_assessment_query_parameter(
    client, mock_db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page sends ?assessment_id=...; the route must draft that rubric."""
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    run_course = _fake_rubric_model(monkeypatch)
    db, org_id, user_id, course = await _workspace()
    older = await service.create_rubric(db, org_id, course.id, user_id, "Older")
    await service.create_rubric(db, org_id, course.id, user_id, "Newer")

    user = MagicMock()
    user.id = user_id
    user.has_role.return_value = True
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)

    response = await client.post(
        f"{settings.API_V1_STR}/profassist/courses/{course.id}/assessment/draft",
        params={"assessment_id": older["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == older["id"]
    assert [item["name"] for item in response.json()["criteria"]] == ["Drafted criterion"]
    run_course.assert_called_once()


@pytest.mark.anyio
async def test_import_route_accepts_the_pasted_form_field(client, mock_db_session) -> None:
    """The page sends FormData(pasted=...). The route must parse and save it."""
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Via route")

    user = MagicMock()
    user.id = user_id
    user.has_role.return_value = True
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)

    response = await client.post(
        f"{settings.API_V1_STR}/profassist/assessments/{created['id']}/import",
        data={"pasted": PASTED},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["name"] for item in payload["criteria"]] == ["Evidence", "Style"]
    persisted = await service.get_assessment(db, org_id, course.id, user_id)
    assert persisted is not None
    assert len(persisted["criteria"]) == 2


@pytest.mark.anyio
async def test_save_route_accepts_json_and_rejects_malformed_criteria(
    client, mock_db_session
) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    db, org_id, user_id, course = await _workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Via JSON")

    user = MagicMock()
    user.id = user_id
    user.has_role.return_value = True
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)

    ok = await client.put(
        f"{settings.API_V1_STR}/profassist/assessments/{created['id']}/rubric",
        json={"brief": "Brief", "criteria": _criteria()},
    )
    assert ok.status_code == 200, ok.text
    assert [item["weight"] for item in ok.json()["criteria"]] == [40, 60]

    bad = await client.put(
        f"{settings.API_V1_STR}/profassist/assessments/{created['id']}/rubric",
        json={"brief": "Brief", "criteria": ["junk"]},
    )
    assert bad.status_code == 400, bad.text
