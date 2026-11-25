"""The home briefing: owner-scoped facts, a bounded draft, and an honest fallback."""

import json
import uuid
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.profassist import agents, briefing, service
from app.profassist.errors import ProfassistError
from app.profassist.models import (
    Course,
    CourseDossier,
    GradeDraft,
    Material,
    Reflection,
    Student,
)
from tests.test_profassist_rubric import FakeSession

BODY = {
    "summary": "A course about assurance.",
    "topics": [{"name": "Evidence", "week": 1}],
    "assessments": [{"name": "Report", "weight": 40}],
    "conflicts": [{"field": "weight", "winner": "outline"}],
}


def _material(org_id, course_id, owner, filename="notes.pdf", status="ready"):
    return Material(
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=owner,
        filename=filename,
        status=status,
        pii_report={},
    )


def _dossier(org_id, course_id, owner, *, status="ready", body=None):
    return CourseDossier(
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=owner,
        status=status,
        body=dict(body) if body is not None else dict(BODY),
    )


async def _workspace():
    db = FakeSession()
    org_id, other_org = uuid.uuid4(), uuid.uuid4()
    user_id, other_user = uuid.uuid4(), uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email="prof@example.com",
            hashed_password="x",
            full_name="Dr Pat",
            role="user",
            is_active=True,
            is_app_admin=False,
        )
    )
    db.add(OrganizationMember(organization_id=org_id, user_id=user_id, role="owner"))
    db.add(
        Organization(
            id=org_id,
            name="Assurance University",
            slug=f"org-{org_id.hex[:12]}",
            created_by_user_id=user_id,
        )
    )
    db.add(
        Organization(
            id=other_org,
            name="Other University",
            slug=f"org-{other_org.hex[:12]}",
            created_by_user_id=user_id,
        )
    )
    course = Course(organization_id=org_id, code="AAA101", title="Assurance Studio", term="2026")
    second = Course(organization_id=org_id, code="AAA102", title="Assurance Lab", term="2026")
    third = Course(organization_id=org_id, code="AAA103", title="Assurance Practice", term="2026")
    fourth = Course(organization_id=org_id, code="AAA104", title="Assurance Seminar", term="2026")
    foreign = Course(organization_id=other_org, code="BBB101", title="Other org", term="2026")
    for row in (course, second, third, fourth, foreign):
        db.add(row)
    await db.flush()
    return db, org_id, user_id, other_user, other_org, course, second, third, fourth, foreign


@pytest.mark.anyio
async def test_briefing_facts_are_owner_and_org_scoped(monkeypatch) -> None:
    (
        db,
        org_id,
        user_id,
        other_user,
        other_org,
        course,
        second,
        _third,
        _fourth,
        foreign,
    ) = await _workspace()
    db.add(_material(org_id, course.id, user_id, "mine.pdf"))
    db.add(_material(org_id, course.id, other_user, "theirs.pdf"))
    db.add(_material(other_org, foreign.id, user_id, "foreign.pdf"))
    db.add(_material(org_id, course.id, user_id, "broken.pdf", status="error"))
    db.add(_dossier(org_id, course.id, user_id))
    db.add(_dossier(org_id, course.id, other_user))
    db.add(_dossier(org_id, second.id, user_id, status="pending"))
    db.add(
        Student(
            organization_id=org_id,
            course_id=course.id,
            external_id="s1",
            display_name="Sara Student",
        )
    )
    db.add(
        Reflection(
            organization_id=org_id,
            owner_user_id=user_id,
            proposal="Keep feedback short.",
            status="proposed",
        )
    )
    db.add(
        Reflection(
            organization_id=org_id,
            owner_user_id=user_id,
            proposal="Old portrait",
            status="approved",
        )
    )
    db.add(
        Reflection(
            organization_id=org_id,
            owner_user_id=other_user,
            proposal="Not mine",
            status="proposed",
        )
    )
    db.add(
        GradeDraft(
            organization_id=org_id,
            owner_user_id=user_id,
            submission_id=uuid.uuid4(),
            status="draft",
        )
    )
    await db.flush()

    captured: dict = {}
    request_thread = get_ident()

    def fake(facts: dict) -> dict:
        captured["facts"] = facts
        captured["thread"] = get_ident()
        return {
            "headline": "One thing",
            "bullets": ["a", "b", "c"],
            "focus": "Review the draft",
            "trace_url": "http://langfuse.local/trace/1",
        }

    monkeypatch.setattr(agents, "run_briefing", fake)

    result = await briefing.build_briefing(db, org_id, user_id)

    assert captured["thread"] != request_thread
    facts = captured["facts"]
    assert facts["professor"] == {
        "name": "Dr Pat",
        "role": "owner",
        "courses": ["AAA101"],
    }
    assert facts["counts"]["ready_materials"] == 1
    assert facts["counts"]["ready_dossiers"] == 1
    assert facts["counts"]["open_reflections"] == 1
    assert facts["counts"]["waiting_approval"] == 1
    assert facts["counts"]["courses"] == 4
    assert facts["counts"]["courses_listed"] == 3
    assert [row["code"] for row in facts["courses"]] == ["AAA101", "AAA102", "AAA103"]
    assert facts["memory"]["topics"] == ["Evidence"]
    assert facts["memory"]["assessments"] == ["Report"]
    assert facts["memory"]["conflicts"] == ["weight: outline"]
    assert facts["reflection"]["latest"] == "Keep feedback short."
    assert "Sara Student" not in json.dumps(facts)
    assert result["trace_url"] == "http://langfuse.local/trace/1"
    assert result["memory"] == {
        "documents": 1,
        "topics": 1,
        "assessments": 1,
        "conflicts": 1,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("error", [ProfassistError(503, "busy"), RuntimeError("bad json")])
async def test_briefing_falls_back_when_the_model_fails(monkeypatch, error) -> None:
    (
        db,
        org_id,
        user_id,
        _other_user,
        _org,
        _course,
        _second,
        _third,
        _fourth,
        _foreign,
    ) = await _workspace()
    for _index in range(2):
        db.add(
            GradeDraft(
                organization_id=org_id,
                owner_user_id=user_id,
                submission_id=uuid.uuid4(),
                status="draft",
            )
        )
    await db.flush()

    def boom(facts: dict) -> dict:
        raise error

    monkeypatch.setattr(agents, "run_briefing", boom)

    result = await briefing.build_briefing(db, org_id, user_id)

    assert result["degraded"] is True
    assert result["trace_url"] is None
    assert "2 grade drafts in progress" in result["headline"]
    assert len(result["bullets"]) == 3
    assert all(len(bullet) <= 240 for bullet in result["bullets"])
    assert result["focus_href"] == "/grade"


@pytest.mark.anyio
async def test_briefing_caps_headline_and_bullets(monkeypatch) -> None:
    db, org_id, user_id, *_rest = await _workspace()
    monkeypatch.setattr(
        agents,
        "run_briefing",
        lambda facts: {
            "headline": "x" * 200,
            "bullets": ["y" * 300 for _ in range(5)],
            "focus": "Review the queue",
            "trace_url": None,
        },
    )

    result = await briefing.build_briefing(db, org_id, user_id)

    assert len(result["headline"]) == 90
    assert len(result["bullets"]) == 3
    assert all(len(bullet) <= 240 for bullet in result["bullets"])


@pytest.mark.anyio
async def test_home_keeps_existing_keys_and_adds_professor_and_memory() -> None:
    (
        db,
        org_id,
        user_id,
        _other_user,
        _org,
        course,
        _second,
        _third,
        _fourth,
        _foreign,
    ) = await _workspace()
    db.add(_material(org_id, course.id, user_id))
    db.add(_dossier(org_id, course.id, user_id))
    db.add(
        Reflection(
            organization_id=org_id,
            owner_user_id=user_id,
            proposal="Keep feedback short.",
            status="proposed",
        )
    )
    await db.flush()

    payload = await service.home(db, org_id, user_id)

    existing = {
        "courses",
        "submissions",
        "drafts",
        "approved",
        "pushed",
        "open_flags",
        "moodle_mode",
        "llm_mode",
        "calibrator",
        "early_warning",
        "principle",
    }
    assert existing.issubset(payload)
    assert payload["professor"] == {
        "name": "Dr Pat",
        "role": "owner",
        "organization": "Assurance University",
        "courses": ["AAA101"],
    }
    assert payload["memory"] == {
        "documents": 1,
        "topics": 1,
        "assessments": 1,
        "reflections": 1,
    }


@pytest.mark.anyio
async def test_home_briefing_endpoint_returns_the_fallback_not_a_503(client, monkeypatch) -> None:
    (
        db,
        org_id,
        user_id,
        _other_user,
        _org,
        _course,
        _second,
        _third,
        _fourth,
        _foreign,
    ) = await _workspace()
    db.add(
        GradeDraft(
            organization_id=org_id,
            owner_user_id=user_id,
            submission_id=uuid.uuid4(),
            status="draft",
        )
    )
    await db.flush()
    monkeypatch.setattr(agents, "run_briefing", MagicMock(side_effect=ProfassistError(503, "busy")))

    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    user = MagicMock()
    user.id = user_id
    user.has_role.return_value = True
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)

    response = await client.post(f"{settings.API_V1_STR}/profassist/home/briefing", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["degraded"] is True
    assert payload["trace_url"] is None
    assert payload["focus_href"] == "/grade"
    assert len(payload["bullets"]) == 3
