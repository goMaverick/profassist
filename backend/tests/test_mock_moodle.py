"""The local Moodle simulator, the connector's activity pull, and the demo scores.

The fake ``AsyncSession`` below is the same small in-memory stand-in used by
``test_moodle_connection.py``: it lets the real service functions run without a
database. Every row here is fictional.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import DateTime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.elements import BindParameter, Null

from app.profassist.errors import ProfassistError
from app.profassist.ml.dropout import FEATURE_COLUMNS, predict
from app.profassist.models import (
    Assessment,
    Course,
    MoodleActivity,
    RubricCriterion,
    Student,
    Submission,
)
from app.profassist.moodle import (
    FakeMoodleConnector,
    MoodleConnectionSpec,
    RealMoodleConnector,
)
from app.profassist.moodle_connection import activity_log_state, get_view
from app.profassist.service import list_students, pull_moodle
from app.profassist.similarity import compare_submissions
from mock_moodle import data as store
from mock_moodle import main as mock

_REVIEW = {"1001": 0.975, "1002": 0.976, "1003": 0.704, "1004": 0.971, "1005": 0.65}
_ROUTINE = {
    "1006": 0.043,
    "1007": 0.038,
    "1008": 0.044,
    "1009": 0.087,
    "1010": 0.048,
    "1011": 0.071,
    "1012": 0.093,
}


# -- in-memory session -----------------------------------------------------


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self.first()


def _criteria(statement) -> list[tuple[str, object]]:
    filters: list[tuple[str, object]] = []
    for criterion in getattr(statement, "_where_criteria", ()):
        key = getattr(getattr(criterion, "left", None), "key", None)
        if not key:
            continue
        right = getattr(criterion, "right", None)
        if isinstance(right, Null):
            filters.append((key, None))
        elif isinstance(right, BindParameter):
            filters.append((key, right.value))
    return filters


def _matches(row: object, filters: list[tuple[str, object]]) -> bool:
    return all(getattr(row, key, object()) == value for key, value in filters)


def _apply_defaults(row: object) -> None:
    for attr in sa_inspect(type(row)).mapper.column_attrs:
        if getattr(row, attr.key, None) is not None:
            continue
        column = attr.columns[0]
        default = column.default
        value: object | None = None
        if default is not None:
            arg = default.arg
            if callable(arg):
                try:
                    value = arg(None)
                except TypeError:
                    value = arg()
            else:
                value = arg
        elif column.server_default is not None and isinstance(column.type, DateTime):
            value = datetime.now(UTC)
        else:
            continue
        setattr(row, attr.key, value)


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[object] = []
        self.commits = 0

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            _apply_defaults(row)

    async def commit(self) -> None:
        self.commits += 1

    async def get(self, model, row_id):
        for row in self.rows:
            if isinstance(row, model) and getattr(row, "id", None) == row_id:
                return row
        return None

    async def execute(self, statement):
        if isinstance(statement, Delete):
            entity = statement.entity_description["entity"]
            filters = _criteria(statement)
            self.rows[:] = [
                row for row in self.rows if not (isinstance(row, entity) and _matches(row, filters))
            ]
            return _Result([])
        description = statement.column_descriptions[0]
        entity = description["entity"]
        filters = _criteria(statement)
        matched = [row for row in self.rows if isinstance(row, entity) and _matches(row, filters)]
        if description.get("expr") is entity:
            return _Result(matched)
        return _Result([getattr(row, description["name"]) for row in matched])


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def moodle_store():
    store.reset()
    yield store
    store.reset()


@pytest.fixture
def clean_integrity_board():
    from app.profassist.integrity_board import unregister_course

    unregister_course("PIPE903")
    yield
    unregister_course("PIPE903")


@pytest.fixture
async def moodle_client():
    store.reset()
    async with AsyncClient(
        transport=ASGITransport(app=mock.app), base_url="http://moodle"
    ) as client:
        yield client
    store.reset()


def _params(function: str, **extra: str) -> dict[str, str]:
    return {
        "wstoken": store.TOKEN,
        "wsfunction": function,
        "moodlewsrestformat": "json",
        **extra,
    }


def _connector() -> RealMoodleConnector:
    return RealMoodleConnector(
        MoodleConnectionSpec(base_url="http://moodle-mock:8090", token=store.TOKEN)
    )


def _full_features() -> dict[str, object]:
    return dict(store.ACTIVITY[1001])


def _partial_features() -> dict[str, object]:
    return {"active_days_14d": 4}


class _ActivityConnector:
    mode = "real"

    def __init__(self, activity: list[dict[str, object]], fail: bool = False) -> None:
        self.activity = activity
        self.fail = fail

    def list_courses(self) -> list[dict[str, object]]:
        return [{"id": "903", "code": "PIPE903", "title": "Integrity", "term": ""}]

    def list_students(self, course_external_id: str) -> list[dict[str, object]]:
        del course_external_id
        return []

    def list_assignments(self, course_external_id: str) -> list[dict[str, object]]:
        del course_external_id
        return []

    def list_workshops(self, course_external_id: str) -> list[dict[str, object]]:
        del course_external_id
        return []

    def list_activity(self, course_external_id: str) -> list[dict[str, object]]:
        del course_external_id
        if self.fail:
            raise ProfassistError(
                503,
                "Moodle refused local_profassist_get_activity: Invalid function name.",
            )
        return self.activity


# -- HTTP simulator --------------------------------------------------------


@pytest.mark.anyio
async def test_health_answers(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "moodle-mock"


@pytest.mark.anyio
async def test_a_wrong_token_is_an_invalidtoken_error(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params={**_params("core_course_get_courses"), "wstoken": "wrong-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exception"] == "webservice_access_exception"
    assert body["errorcode"] == "invalidtoken"
    assert "wrong-token" not in str(body)


@pytest.mark.anyio
async def test_a_missing_token_is_also_refused(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params={"wsfunction": "core_course_get_courses"},
    )

    assert response.json()["errorcode"] == "invalidtoken"


@pytest.mark.anyio
async def test_an_unknown_function_is_invalidfunction(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php", params=_params("local_not_a_function")
    )

    body = response.json()
    assert body["errorcode"] == "invalidfunction"
    assert "local_not_a_function" in body["message"]


@pytest.mark.anyio
async def test_site_info_lists_the_implemented_functions(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php", params=_params("core_webservice_get_site_info")
    )

    body = response.json()
    names = {item["name"] for item in body["functions"]}
    assert body["sitename"] == "ProfAssist Demo Moodle"
    assert body["downloadfiles"] == 1
    assert "local_profassist_get_activity" in names
    assert "mod_assign_get_submissions" in names
    assert body["warnings"] == []


@pytest.mark.anyio
async def test_course_reads_include_the_front_page_and_pipe903(
    moodle_client: AsyncClient,
) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php", params=_params("core_course_get_courses")
    )

    rows = response.json()
    assert [row["id"] for row in rows] == [1, 903]
    assert rows[1]["shortname"] == "PIPE903"
    assert rows[0]["format"] == "site"


@pytest.mark.anyio
async def test_courses_by_field_finds_the_course(moodle_client: AsyncClient) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params(
            "core_course_get_courses_by_field",
            field="idnumber",
            value="PIPE903",
        ),
    )

    body = response.json()
    assert [row["id"] for row in body["courses"]] == [903]
    assert body["warnings"] == []


@pytest.mark.anyio
async def test_course_create_and_update_return_ids(moodle_client: AsyncClient) -> None:
    created = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_course_create_courses",
            **{
                "courses[0][shortname]": "DEMO101",
                "courses[0][fullname]": "Demo course",
                "courses[0][idnumber]": "DEMO101",
            },
        ),
    )
    body = created.json()
    assert body["warnings"] == []
    assert len(body["courses"]) == 1
    course_id = body["courses"][0]["id"]
    assert course_id == 904

    found = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_course_get_courses_by_field", field="idnumber", value="DEMO101"),
    )
    assert found.json()["courses"][0]["fullname"] == "Demo course"

    updated = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_course_update_courses",
            **{"courses[0][id]": str(course_id), "courses[0][fullname]": "Updated course"},
        ),
    )
    assert updated.json()["courses"] == [
        {"id": course_id, "shortname": "DEMO101", "fullname": "Updated course"}
    ]


@pytest.mark.anyio
async def test_a_duplicate_shortname_is_a_warning(moodle_client: AsyncClient) -> None:
    response = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_course_create_courses",
            **{"courses[0][shortname]": "PIPE903", "courses[0][fullname]": "Again"},
        ),
    )

    body = response.json()
    assert body["courses"] == []
    assert body["warnings"][0]["warningcode"] == "shortnametaken"


@pytest.mark.anyio
async def test_user_create_and_update_return_ids(moodle_client: AsyncClient) -> None:
    created = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_user_create_users",
            **{
                "users[0][username]": "new.student",
                "users[0][email]": "new.student@demo.invalid",
                "users[0][firstname]": "New",
                "users[0][lastname]": "Student",
            },
        ),
    )
    body = created.json()
    user_id = body["users"][0]["id"]
    assert user_id == 1013
    assert body["users"][0]["username"] == "new.student"

    updated = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_user_update_users",
            **{"users[0][id]": str(user_id), "users[0][lastname]": "Learner"},
        ),
    )
    assert updated.json()["users"] == [{"id": user_id, "username": "new.student"}]

    profiles = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params(
            "core_user_get_course_user_profiles",
            **{"userlist[0][userid]": str(user_id), "userlist[0][courseid]": "903"},
        ),
    )
    assert profiles.json()[0]["fullname"] == "New Learner"


@pytest.mark.anyio
async def test_enrolment_returns_the_twelve_seeded_students(
    moodle_client: AsyncClient,
) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_enrol_get_enrolled_users", courseid="903"),
    )

    users = response.json()
    assert len(users) == 12
    assert [user["id"] for user in users] == list(range(1001, 1013))
    assert users[0]["idnumber"] == "8881001"


@pytest.mark.anyio
async def test_a_new_student_can_be_enrolled_and_read_back(
    moodle_client: AsyncClient,
) -> None:
    await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "core_user_create_users",
            **{"users[0][username]": "later.student", "users[0][email]": "later@demo.invalid"},
        ),
    )
    enrolled = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "enrol_manual_enrol_users",
            **{"enrolments[0][courseid]": "903", "enrolments[0][userid]": "1013"},
        ),
    )
    assert enrolled.json()["warnings"] == []

    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_enrol_get_enrolled_users", courseid="903"),
    )
    assert [user["id"] for user in response.json()][-1] == 1013


@pytest.mark.anyio
async def test_assignments_and_the_rubric_are_moodle_shaped(
    moodle_client: AsyncClient,
) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("mod_assign_get_assignments", **{"courseids[0]": "903"}),
    )

    body = response.json()
    assignments = body["courses"][0]["assignments"]
    assert [row["id"] for row in assignments] == [901, 902]
    assert assignments[0]["cmid"] == 1901
    assert body["warnings"] == []

    rubric = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_grading_get_definitions", **{"cmids[0]": "1901"}),
    )
    definitions = rubric.json()["areas"][0]["definitions"][0]
    assert definitions["rubric"]["criteria"][0]["description"] == "Evidence and analysis"
    assert len(definitions["rubric"]["criteria"]) == 3


@pytest.mark.anyio
async def test_submissions_are_latest_and_share_the_three_passages(
    moodle_client: AsyncClient,
) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params(
            "mod_assign_get_submissions",
            **{"assignmentids[0]": "901", "status": "submitted"},
        ),
    )

    submissions = response.json()["assignments"][0]["submissions"]
    assert len(submissions) == 6
    assert all(row["latest"] == 1 for row in submissions)
    assert all(row["status"] == "submitted" for row in submissions)
    texts = [row["plugins"][0]["editorfields"][0]["text"] for row in submissions]
    rows = [
        {
            "id": str(row["id"]),
            "group_name": f"Group {chr(64 + index + 1)}",
            "topic": "moodle",
            "text": text,
        }
        for index, (row, text) in enumerate(zip(submissions, texts, strict=True))
    ]
    flags = compare_submissions(rows)
    pairs = {(flag["left_group"], flag["right_group"], flag["section"]) for flag in flags}
    assert pairs == {
        ("Group A", "Group B", "method"),
        ("Group C", "Group D", "findings"),
        ("Group E", "Group F", "introduction"),
    }
    assert all(flag["score"] == 1.0 for flag in flags)


@pytest.mark.anyio
async def test_groups_and_members_cover_a_to_f(moodle_client: AsyncClient) -> None:
    groups = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_group_get_course_groups", courseid="903"),
    )
    assert [row["name"] for row in groups.json()] == [f"Group {letter}" for letter in "ABCDEF"]

    members = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_group_get_group_members", courseid="903"),
    )
    rows = members.json()
    assert len(rows) == 6
    assert [row["members"][0]["id"] for row in rows] == [1001, 1003, 1005, 1007, 1009, 1011]


@pytest.mark.anyio
async def test_activity_returns_twelve_complete_feature_rows(
    moodle_client: AsyncClient,
) -> None:
    response = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("local_profassist_get_activity", courseid="903"),
    )

    body = response.json()
    assert body["warnings"] == []
    assert len(body["students"]) == 12
    assert [row["userid"] for row in body["students"]] == list(range(1001, 1013))
    assert all(set(row["features"]) == set(FEATURE_COLUMNS) for row in body["students"])


@pytest.mark.anyio
async def test_unknown_courses_return_warnings_not_errors(
    moodle_client: AsyncClient,
) -> None:
    enrolled = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("core_enrol_get_enrolled_users", courseid="999"),
    )
    assert enrolled.json()["users"] == []
    assert enrolled.json()["warnings"][0]["warningcode"] == "notfound"

    activity = await moodle_client.get(
        "/webservice/rest/server.php",
        params=_params("local_profassist_get_activity", courseid="999"),
    )
    assert activity.json()["students"] == []
    assert activity.json()["warnings"][0]["warningcode"] == "notfound"


@pytest.mark.anyio
async def test_saving_a_grade_is_recorded(moodle_client: AsyncClient) -> None:
    response = await moodle_client.post(
        "/webservice/rest/server.php",
        data=_params(
            "mod_assign_save_grade",
            assignmentid="901",
            userid="1001",
            grade="72",
            **{"plugindata[assignfeedbackcomments_editor][text]": "Clear method."},
        ),
    )

    body = response.json()
    assert body["warnings"] == []
    assert body["savedgrade"] == 72.0
    assert store.GRADES[(901, 1001)]["feedback"] == "Clear method."


# -- connector -------------------------------------------------------------


def test_the_fake_connector_has_no_activity() -> None:
    assert FakeMoodleConnector().list_activity("903") == []


def test_the_connector_reads_activity_from_the_mock(moodle_store) -> None:
    client = _connector()
    client._ws = lambda function, params: mock.dispatch(function, params)  # type: ignore[method-assign]

    rows = client.list_activity("903")

    assert len(rows) == 12
    assert rows[0]["userid"] == "1001"
    assert set(rows[0]["features"]) == set(FEATURE_COLUMNS)
    assert rows[0]["features"]["active_days_14d"] == 0


def test_missing_activity_columns_stay_none() -> None:
    client = _connector()
    client._ws = lambda function, params: {  # type: ignore[method-assign]
        "students": [{"userid": 1001, "features": {"active_days_14d": 4, "extra": 9}}],
        "warnings": [],
    }

    rows = client.list_activity("903")

    assert rows[0]["features"]["active_days_14d"] == 4
    assert rows[0]["features"]["interactions_14d"] is None
    assert "extra" not in rows[0]["features"]


# -- service ---------------------------------------------------------------


@pytest.mark.anyio
async def test_pull_moodle_ingests_the_whole_demo_site(clean_integrity_board) -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    connector = _connector()
    connector._ws = lambda function, params: mock.dispatch(function, params)  # type: ignore[method-assign]

    first = await pull_moodle(db, org_id, None, connector)

    counts = {
        "courses": sum(isinstance(row, Course) for row in db.rows),
        "students": sum(isinstance(row, Student) for row in db.rows),
        "assessments": sum(isinstance(row, Assessment) for row in db.rows),
        "submissions": sum(isinstance(row, Submission) for row in db.rows),
        "criteria": sum(isinstance(row, RubricCriterion) for row in db.rows),
        "activity": sum(isinstance(row, MoodleActivity) for row in db.rows),
    }
    assert counts == {
        "courses": 1,
        "students": 12,
        "assessments": 2,
        "submissions": 6,
        "criteria": 3,
        "activity": 12,
    }
    assert first["submissions"] == 6
    assert "PIPE903" in {row.code for row in db.rows if isinstance(row, Course)}
    assert {row.group_name for row in db.rows if isinstance(row, Submission)} == {
        f"Group {letter}" for letter in "ABCDEF"
    }

    from app.profassist.integrity_board import assignment_matrix, overview

    board = overview("PIPE903")
    assert board["summary"]["assignments"] == 1
    card = board["items"][0]
    assert card["status"] == "Concern"
    assert card["flagged_pairs"] == 3
    matrix = assignment_matrix("PIPE903", card["number"])
    flagged = {
        (pair["left"], pair["right"]) for pair in matrix["pairs"] if pair["status"] != "Clear"
    }
    assert flagged == {("A", "B"), ("C", "D"), ("E", "F")}

    await pull_moodle(db, org_id, None, connector)

    assert sum(isinstance(row, Course) for row in db.rows) == 1
    assert sum(isinstance(row, Student) for row in db.rows) == 12
    assert sum(isinstance(row, Assessment) for row in db.rows) == 2
    assert sum(isinstance(row, Submission) for row in db.rows) == 6
    assert sum(isinstance(row, RubricCriterion) for row in db.rows) == 3
    assert sum(isinstance(row, MoodleActivity) for row in db.rows) == 12


@pytest.mark.anyio
async def test_pull_moodle_stores_features_idempotently() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    activity = [
        {"userid": "1001", "features": _full_features()},
        {"userid": "1002", "features": dict(store.ACTIVITY[1002])},
    ]
    connector = _ActivityConnector(activity)

    first = await pull_moodle(db, org_id, None, connector)
    rows = [row for row in db.rows if isinstance(row, MoodleActivity)]
    assert len(rows) == 2
    assert {row.student_external_id for row in rows} == {"1001", "1002"}
    assert all(row.source == "real" for row in rows)
    assert all(row.synced_at is not None for row in rows)
    assert "Activity features stored for 2 students." in first["last_sync_status"]

    second = await pull_moodle(db, org_id, None, connector)
    rows = [row for row in db.rows if isinstance(row, MoodleActivity)]
    assert len(rows) == 2
    assert "Activity features stored for 2 students." in second["last_sync_status"]


@pytest.mark.anyio
async def test_pull_moodle_continues_when_activity_is_unavailable() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    connector = _ActivityConnector([], fail=True)

    result = await pull_moodle(db, org_id, None, connector)

    assert [row for row in db.rows if isinstance(row, MoodleActivity)] == []
    assert "Activity features were not available" in result["last_sync_status"]


@pytest.mark.anyio
async def test_list_students_scores_only_complete_activity_rows() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    course = Course(
        id=uuid.uuid4(),
        organization_id=org_id,
        code="PIPE903",
        title="Integrity",
    )
    sara = Student(
        organization_id=org_id,
        course_id=course.id,
        external_id="1001",
        display_name="Sara Al Maktoum",
        email="sara@demo.invalid",
        student_number="8881001",
    )
    omar = Student(
        organization_id=org_id,
        course_id=course.id,
        external_id="1002",
        display_name="Omar Haddad",
        email="omar@demo.invalid",
        student_number="8881002",
    )
    complete = MoodleActivity(
        organization_id=org_id,
        course_id=course.id,
        student_external_id="1001",
        features=_full_features(),
    )
    partial = MoodleActivity(
        organization_id=org_id,
        course_id=course.id,
        student_external_id="1002",
        features=_partial_features(),
    )
    db.rows.extend([course, sara, omar, complete, partial])

    payload = await list_students(db, org_id, course.id)

    scored = {row["external_id"]: row for row in payload["early_warning"]["students"]}
    assert scored["1001"]["score"] == pytest.approx(0.975, abs=1e-9)
    assert scored["1001"]["band"] == "review"
    assert scored["1002"]["score"] is None
    assert scored["1002"]["band"] is None
    assert payload["early_warning"]["synthetic"] is True


def test_the_twelve_demo_rows_score_five_review_and_seven_routine() -> None:
    store.reset()
    students = [
        {"external_id": str(userid), "display_name": store.USERS[userid]["fullname"]}
        for userid in sorted(store.ACTIVITY)
    ]

    payload = predict(
        students,
        course_code="PIPE903",
        features_by_student={str(key): value for key, value in store.ACTIVITY.items()},
    )

    scores = {row["external_id"]: row["score"] for row in payload["students"]}
    assert scores == pytest.approx({**_REVIEW, **_ROUTINE}, abs=1e-9)
    assert [row["band"] for row in payload["students"]] == ["review"] * 5 + ["routine"] * 7
    assert payload["status"] == "trained"
    assert payload["trained"] is True
    assert payload["synthetic"] is True
    assert payload["threshold"] == 0.1
    assert payload["automatic_actions"] is False


@pytest.mark.anyio
async def test_activity_log_state_is_honest_about_the_demo_function() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    missing = await activity_log_state(db, org_id)
    assert missing["available"] is False
    assert "local_profassist_get_activity" in missing["reason"]

    db.rows.append(
        MoodleActivity(
            organization_id=org_id,
            course_id=uuid.uuid4(),
            student_external_id="1001",
            features=_full_features(),
        )
    )
    present = await activity_log_state(db, org_id)
    assert present["available"] is True
    assert "demo-only" in present["reason"]


@pytest.mark.anyio
async def test_the_connection_view_shows_the_env_fallback_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOODLE_MODE", "real")
    monkeypatch.setenv("MOODLE_BASE_URL", "http://moodle-mock:8090")
    monkeypatch.setenv("MOODLE_WS_TOKEN", "demo-token")

    view = await get_view(FakeSession(), uuid.uuid4())

    assert view["configured"] is False
    assert view["env_fallback"]["available"] is True
    assert view["env_fallback"]["base_url"] == "http://moodle-mock:8090"
    assert view["env_fallback"]["token_configured"] is True
    assert "demo-token" not in str(view)


# -- schema and compose ----------------------------------------------------


def test_the_model_declares_the_features_jsonb_column() -> None:
    column = MoodleActivity.__table__.c.features
    assert isinstance(column.type, JSONB)
    assert column.nullable is False


def test_migration_0042_follows_0041_and_adds_the_column() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "alembic" / "versions" / "0042_moodle_activity_features.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0042_moodle_activity_features"' in source
    assert 'down_revision = "0041_moodle_connection"' in source
    assert "op.add_column(" in source
    assert '"pa_moodle_activity"' in source
    assert '"features"' in source
    assert "JSONB" in source
    assert 'op.drop_column("pa_moodle_activity", "features")' in source


def test_compose_runs_the_mock_and_points_the_workers_at_it() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["moodle-mock"]

    assert service["image"] == "profassist_backend:dev"
    assert service["command"] == [
        "uvicorn",
        "mock_moodle.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8090",
    ]
    assert "./backend/mock_moodle:/app/mock_moodle:ro" in service["volumes"]
    assert "8090:8090" in service["ports"]
    assert service["healthcheck"]["test"]

    for name in ("app", "prefect-runner"):
        environment = compose["services"][name]["environment"]
        for value in (
            "MOODLE_MODE=real",
            "MOODLE_BASE_URL=http://moodle-mock:8090",
            "MOODLE_WS_TOKEN=demo-token",
            "MOODLE_ALLOW_PRIVATE=true",
        ):
            assert value in environment
