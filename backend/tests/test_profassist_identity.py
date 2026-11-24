"""The portrait follows the signed-in professor, never another tenant."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.profassist import agents, service, settings_admin
from app.profassist.lessons import condense_about, split_identity
from app.profassist.models import Course, CourseDesign, Reflection, StyleProfile
from tests.test_profassist_rubric import FakeSession


def _person(db: FakeSession, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.add(User(id=user_id, email="jane@university.edu", full_name="Jane Doe", role="user"))
    db.add(OrganizationMember(organization_id=org_id, user_id=user_id, role="owner"))


def test_condense_about_carries_identity_and_never_email() -> None:
    portrait = condense_about(
        "Short sentences.",
        [{"kind": "tone", "text": "Write feedback without exclamation marks."}],
        [],
        {
            "name": "Jane Doe",
            "role": "owner",
            "courses": ["AAS910", "BIO201"],
            "email": "jane@university.edu",
        },
    )

    assert "Professor: Jane Doe \u2014 owner" in portrait
    assert "Teaches: AAS910, BIO201" in portrait
    assert "tone: Write feedback without exclamation marks." in portrait
    assert "@" not in portrait
    assert len(portrait) <= 900


def test_split_identity_keeps_the_name_out_of_the_pii_body() -> None:
    identity, body = split_identity(
        "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nShort."
    )

    assert identity == ["Professor: Jane Doe \u2014 owner", "Teaches: AAS910"]
    assert "Jane Doe" not in body


@pytest.mark.anyio
async def test_prime_about_uses_the_signed_in_name_and_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, other_org, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    own = Course(id=uuid.uuid4(), organization_id=org_id, code="AAS910", title="Assurance")
    foreign = Course(id=uuid.uuid4(), organization_id=other_org, code="ZZZ999", title="Elsewhere")
    db.add(own)
    db.add(foreign)
    db.add(CourseDesign(organization_id=org_id, course_id=own.id, owner_user_id=user_id))
    db.add(CourseDesign(organization_id=other_org, course_id=foreign.id, owner_user_id=user_id))
    await db.flush()
    seen: dict[str, str] = {}
    monkeypatch.setattr(settings_admin, "set_about", lambda text: seen.setdefault("text", text))

    await settings_admin._prime_about(db, org_id, user_id)

    portrait = seen["text"]
    assert "Jane Doe" in portrait
    assert "owner" in portrait
    assert "AAS910" in portrait
    assert "ZZZ999" not in portrait


@pytest.mark.anyio
async def test_identity_does_not_fall_back_to_every_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    db.add(Course(id=uuid.uuid4(), organization_id=org_id, code="ORG101", title="Shared"))
    await db.flush()

    identity = await settings_admin.professor_identity(db, org_id, user_id)

    assert identity["name"] == "Jane Doe"
    assert identity["role"] == "owner"
    assert identity["courses"] == []


@pytest.mark.anyio
async def test_service_run_reflection_passes_the_professor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    run = MagicMock(return_value="A portrait.")
    monkeypatch.setattr(service.agents, "run_reflection", run)

    result = await service.run_reflection(db, org_id, user_id)

    args, kwargs = run.call_args
    assert kwargs["professor"] == identity
    assert "Professor: Jane Doe \u2014 owner" in args[0]
    assert "Teaches: AAS910" in args[0]
    assert "No grade-level changes" in args[0]
    assert result["proposal"] == "A portrait."
    assert result["status"] == "applied"


def test_run_reflection_sends_the_professor_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_complete(task: str, payload: dict) -> dict:
        seen["task"] = task
        seen["payload"] = payload
        return {"proposal": "A portrait."}

    monkeypatch.setattr(agents.llm, "complete", fake_complete)

    text = agents.run_reflection(
        "seed", professor={"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    )

    assert text == "A portrait."
    assert seen["task"] == "reflection"
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["professor"]["name"] == "Jane Doe"
    assert payload["professor"]["courses"] == ["AAS910"]


@pytest.mark.anyio
async def test_approving_a_legacy_proposal_keeps_identity_in_the_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    course = Course(id=uuid.uuid4(), organization_id=org_id, code="AAS910", title="Assurance")
    db.add(course)
    db.add(CourseDesign(organization_id=org_id, course_id=course.id, owner_user_id=user_id))
    row = Reflection(
        organization_id=org_id,
        owner_user_id=user_id,
        proposal="Use shorter feedback.",
        status="proposed",
    )
    db.add(row)
    await db.flush()
    seen: dict[str, str] = {}
    monkeypatch.setattr(service, "set_about", lambda text: seen.setdefault("text", text))

    await service.approve_reflection(db, org_id, user_id, row.id)

    profile = next(item for item in db.rows if isinstance(item, StyleProfile))
    assert row.status == "applied"
    assert "Jane Doe" in profile.about_md
    assert "owner" in profile.about_md
    assert "AAS910" in profile.about_md
    assert seen["text"] == profile.about_md


@pytest.mark.anyio
async def test_saving_the_portrait_keeps_identity_and_scrubs_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    course = Course(id=uuid.uuid4(), organization_id=org_id, code="AAS910", title="Assurance")
    db.add(course)
    db.add(CourseDesign(organization_id=org_id, course_id=course.id, owner_user_id=user_id))
    await db.flush()
    monkeypatch.setattr(service, "set_about", lambda text: None)

    saved = await service.save_about(
        db,
        org_id,
        user_id,
        "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nLead with evidence.",
    )

    assert "Jane Doe" in saved["about_md"]
    assert "AAS910" in saved["about_md"]
    assert "Lead with evidence." in saved["about_md"]
