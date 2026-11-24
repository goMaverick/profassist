"""Council settings: defaults, storage, validation, the admin API, and overrides."""

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Delete
from sqlalchemy.sql.elements import BindParameter, Null

import app.profassist.agents as agents
import app.profassist.assignment_council as assignment_council
import app.profassist.llm as llm
import app.profassist.outline_review as outline_review
from app.core.config import settings
from app.profassist.assignment_data import fixed_report_sections
from app.profassist.council_config import (
    COUNCIL_KEYS,
    council_view,
    default_roles,
    load_council_roles,
    reset_council,
    save_council_roles,
)
from app.profassist.errors import ProfassistError
from app.profassist.models import CouncilRole
from app.profassist.runtime import DEFAULT_PROMPTS

CITED = "Design an end-to-end AI solution (lecture.pdf)."
LEVELS = {
    "beginning": "Little detail.",
    "developing": "Some detail.",
    "proficient": "Clear detail.",
    "advanced": "Insightful detail.",
}


# --- the in-memory session -------------------------------------------------


class _Result:
    def __init__(self, rows: list[Any], count: int = 0) -> None:
        self._rows = list(rows)
        self._count = count

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> int:
        return self._count


def _criteria(statement: Any) -> list[tuple[str, Any]]:
    filters: list[tuple[str, Any]] = []
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


def _matches(row: Any, filters: list[tuple[str, Any]]) -> bool:
    return all(getattr(row, key, object()) == value for key, value in filters)


class _Session:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows: list[Any] = list(rows or [])
        self.flushed = 0

    def add(self, row: Any) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushed += 1

    async def execute(self, statement: Any) -> _Result:
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
        rows.sort(key=lambda row: (getattr(row, "position", 0), getattr(row, "role_key", "")))
        return _Result(rows, count=len(rows))


def _saved(org_id: uuid.UUID, council: str, role: dict[str, Any]) -> CouncilRole:
    return CouncilRole(
        organization_id=org_id,
        council_key=council,
        role_key=role["role_key"],
        label=role["label"],
        kind=role["kind"],
        persona_prompt=role["persona_prompt"],
        agent_key=role["agent_key"],
        model=role["model"],
        position=role["position"],
        enabled=role["enabled"],
        config=role["config"],
        custom=role["custom"],
    )


def _roles(key: str) -> list[dict[str, Any]]:
    return [dict(role) for role in default_roles(key)]


def _set(roles: list[dict[str, Any]], role_key: str, **changes: Any) -> None:
    role = next(item for item in roles if item["role_key"] == role_key)
    role.update(changes)


def _custom(role_key: str = "ethics") -> dict[str, Any]:
    return {
        "role_key": role_key,
        "label": role_key.title(),
        "kind": "llm",
        "persona_prompt": f"Review as {role_key}.",
        "agent_key": "",
        "model": "",
        "position": 0,
        "enabled": True,
        "config": {},
        "custom": True,
    }


def _with_custom(key: str) -> list[dict[str, Any]]:
    roles = _roles(key)
    roles.insert(len(roles) - 1, _custom())
    return roles


def _wire_model(
    monkeypatch: pytest.MonkeyPatch, by_task: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> Any:
        calls.append((task, payload))
        reply = by_task.get(task, {})
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm, "complete", fake_complete)
    return calls


def _deck(**overrides: Any) -> dict[str, Any]:
    deck: dict[str, Any] = {
        "title": "Week 7: Architecture review",
        "slides": [
            {
                "title": "Architecture",
                "objective": "Design an end-to-end AI solution.",
                "bullets": [CITED],
            }
        ],
        "gaps": [],
    }
    deck.update(overrides)
    return deck


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "class_details": {
            "assessment": "Assessment 2: Solutions Architecture Report",
            "weight": "25%",
            "report_due": "Week 7",
        },
        "overview": ["Design an AI solution architecture."],
        "problem_choices": [
            {"problem": "Bank fraud detection", "description": "Real-time scoring."}
        ],
        "deliverables": [{"title": "Technical report", "description": "At most 2,500 words."}],
        "report_sections": fixed_report_sections(),
    }
    document.update(overrides)
    return document


def _rubric() -> list[dict[str, Any]]:
    return [
        {"name": "Architecture", "weight": 60, "levels": dict(LEVELS)},
        {"name": "Ethics", "weight": 40, "levels": dict(LEVELS)},
    ]


def _outline() -> dict[str, Any]:
    return {
        "clos": [{"code": "LO1", "text": "Design an end-to-end AI solution."}],
        "outcome_measures": [{"lo_code": "LO1", "measures": "Assessment 2 report"}],
    }


# --- defaults --------------------------------------------------------------


def test_every_council_has_one_chair_last_and_contiguous_positions() -> None:
    assert COUNCIL_KEYS == ("material", "assignment", "grading", "outline")

    for key in COUNCIL_KEYS:
        roles = default_roles(key)
        assert [role["position"] for role in roles] == list(range(1, len(roles) + 1))
        chairs = [role for role in roles if role["kind"] == "chair"]
        assert [role["role_key"] for role in chairs] == ["chair"]
        assert roles[-1]["role_key"] == "chair"


def test_grading_defaults_are_three_personas_and_a_deterministic_chair() -> None:
    roles = default_roles("grading")

    assert [role["role_key"] for role in roles] == ["evidence", "strict", "supportive", "chair"]
    assert [role["kind"] for role in roles] == ["llm", "llm", "llm", "chair"]
    chair = roles[-1]
    assert chair["config"] == {
        "deterministic": True,
        "judge": "deterministic",
        "prompt_editable": False,
    }
    assert chair["prompt_editable"] is False
    assert roles[0]["prompt_editable"] is True


@pytest.mark.anyio
async def test_outline_defaults_include_the_creator_and_allow_custom_roles() -> None:
    roles = default_roles("outline")

    assert [role["role_key"] for role in roles] == [
        "creator",
        "curriculum",
        "alignment",
        "balance",
        "student",
        "chair",
    ]
    creator = roles[0]
    assert creator["label"] == "Creator"
    assert creator["kind"] == "creator"
    assert creator["persona_prompt"] == DEFAULT_PROMPTS["outline_generate"]
    assert creator["agent_key"] == "course_designer"
    assert creator["position"] == 1

    view = await council_view(_Session(), uuid.uuid4(), "outline")
    assert view["allow_custom"] is True
    assert default_roles("material")[0]["kind"] == "creator"
    assert default_roles("assignment")[0]["kind"] == "creator"
    assert all(role["kind"] != "creator" for role in default_roles("grading"))


# --- the migration ---------------------------------------------------------


def test_council_migration_creates_the_table_after_0042() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0043_council_settings.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0043_council_settings"' in source
    assert 'down_revision = "0042_moodle_activity_features"' in source
    assert '"pa_council_roles"' in source
    assert "uq_pa_council_role" in source


def test_council_migration_applies_the_tenant_policy_and_grant() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0043_council_settings.py"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "pa_council_roles_tenant" in source
    assert "current_setting('app.current_org', true)" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON pa_council_roles TO profassist_app" in source
    assert "DROP POLICY IF EXISTS pa_council_roles_tenant" in source


def test_the_model_matches_the_migration() -> None:
    table = CouncilRole.__table__
    for column in (
        "organization_id",
        "council_key",
        "role_key",
        "label",
        "kind",
        "persona_prompt",
        "agent_key",
        "model",
        "position",
        "enabled",
        "config",
        "custom",
        "created_at",
        "updated_at",
    ):
        assert column in table.columns
    unique = {constraint.name for constraint in table.constraints}
    assert "uq_pa_council_role" in unique


# --- config: load, save, reset, scoping, validation ------------------------


@pytest.mark.anyio
async def test_load_returns_the_defaults_when_nothing_is_saved() -> None:
    db = _Session()

    roles = await load_council_roles(db, uuid.uuid4(), "material")

    assert [role["role_key"] for role in roles] == [
        "creator",
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    assert roles[-1]["prompt_editable"] is True


@pytest.mark.anyio
async def test_saved_rows_load_in_position_order_and_stay_in_their_org() -> None:
    org_id, other = uuid.uuid4(), uuid.uuid4()
    rows = [_saved(org_id, "material", role) for role in _roles("material")]
    for row in rows:
        row.position = {"creator": 4, "curriculum": 1, "evidence": 2, "design": 3, "chair": 5}[
            row.role_key
        ]
    db = _Session(rows)

    mine = await load_council_roles(db, org_id, "material")
    theirs = await load_council_roles(db, other, "material")

    assert [role["role_key"] for role in mine] == [
        "curriculum",
        "evidence",
        "design",
        "creator",
        "chair",
    ]
    assert [role["role_key"] for role in theirs] == [
        "creator",
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]


@pytest.mark.anyio
async def test_save_replaces_the_rows_and_puts_the_chair_last() -> None:
    org_id = uuid.uuid4()
    db = _Session()
    roles = _roles("material")
    chair = roles.pop()
    roles.insert(0, chair)

    view = await save_council_roles(db, org_id, "material", roles)

    assert [role["role_key"] for role in view["roles"]] == [
        "creator",
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    assert [role["position"] for role in view["roles"]] == [1, 2, 3, 4, 5]
    assert [row.role_key for row in db.rows][-1] == "chair"
    assert view["allow_custom"] is True

    loaded = await load_council_roles(db, org_id, "material")
    assert [role["role_key"] for role in loaded] == [
        "creator",
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]


@pytest.mark.anyio
async def test_save_only_replaces_this_orgs_rows() -> None:
    mine, other = uuid.uuid4(), uuid.uuid4()
    other_row = _saved(other, "material", _roles("material")[0])
    db = _Session([other_row])

    await save_council_roles(db, mine, "material", _roles("material"))

    assert other_row in db.rows
    assert {row.organization_id for row in db.rows if row is not other_row} == {mine}


@pytest.mark.anyio
async def test_reset_deletes_this_orgs_rows_and_restores_the_default() -> None:
    org_id, other = uuid.uuid4(), uuid.uuid4()
    other_row = _saved(other, "outline", _roles("outline")[0])
    db = _Session([other_row])

    await save_council_roles(db, org_id, "outline", _roles("outline"))
    view = await reset_council(db, org_id, "outline")

    assert db.rows == [other_row]
    assert [role["role_key"] for role in view["roles"]] == [
        "creator",
        "curriculum",
        "alignment",
        "balance",
        "student",
        "chair",
    ]


@pytest.mark.anyio
async def test_a_bad_council_key_is_a_400() -> None:
    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "moodle", _roles("material"))
    assert caught.value.status == 400

    with pytest.raises(ProfassistError):
        await load_council_roles(_Session(), uuid.uuid4(), "moodle")


@pytest.mark.anyio
async def test_a_duplicate_role_key_is_rejected() -> None:
    roles = _with_custom("material")
    roles.insert(1, _custom())

    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", roles)
    assert caught.value.status == 400
    assert "used once" in caught.value.detail


@pytest.mark.anyio
async def test_exactly_one_chair_is_required() -> None:
    without_chair = [role for role in _roles("material") if role["kind"] != "chair"]

    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", without_chair)
    assert caught.value.status == 400
    assert "one chair" in caught.value.detail

    empty: list[dict[str, Any]] = []
    with pytest.raises(ProfassistError):
        await save_council_roles(_Session(), uuid.uuid4(), "material", empty)


@pytest.mark.anyio
async def test_positions_are_contiguous_from_one() -> None:
    duplicate = _roles("material")
    duplicate[1]["position"] = 3
    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", duplicate)
    assert caught.value.status == 400
    assert "used once" in caught.value.detail

    out_of_range = _roles("material")
    out_of_range[1]["position"] = 99
    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", out_of_range)
    assert caught.value.status == 400

    not_a_number = _roles("material")
    not_a_number[1]["position"] = "middle"
    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", not_a_number)
    assert caught.value.status == 400


@pytest.mark.anyio
async def test_custom_roles_are_allowed_where_the_spec_says() -> None:
    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "grading", _with_custom("grading"))
    assert caught.value.status == 400
    assert "does not accept custom roles" in caught.value.detail

    for key in ("material", "assignment", "outline"):
        view = await save_council_roles(_Session(), uuid.uuid4(), key, _with_custom(key))
        custom = next(role for role in view["roles"] if role["role_key"] == "ethics")
        assert custom["custom"] is True
        assert custom["kind"] == "llm"
        assert custom["prompt_editable"] is True


@pytest.mark.anyio
async def test_a_custom_role_needs_a_persona_prompt() -> None:
    roles = _with_custom("material")
    custom = next(role for role in roles if role["role_key"] == "ethics")
    custom["persona_prompt"] = ""

    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", roles)
    assert caught.value.status == 400


@pytest.mark.anyio
async def test_a_builtin_role_keeps_its_kind() -> None:
    roles = _roles("material")
    _set(roles, "evidence", kind="llm")

    with pytest.raises(ProfassistError) as caught:
        await save_council_roles(_Session(), uuid.uuid4(), "material", roles)
    assert caught.value.status == 400


@pytest.mark.anyio
async def test_council_view_reports_custom_and_editability() -> None:
    db = _Session()

    material = await council_view(db, uuid.uuid4(), "material")
    grading = await council_view(db, uuid.uuid4(), "grading")
    outline = await council_view(db, uuid.uuid4(), "outline")

    assert material["allow_custom"] is True
    assert outline["allow_custom"] is True
    assert outline["roles"][0]["role_key"] == "creator"
    assert grading["allow_custom"] is False
    chair = grading["roles"][-1]
    assert chair["prompt_editable"] is False


# --- material --------------------------------------------------------------


def test_a_disabled_material_reviewer_drops_findings_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("material")
    _set(roles, "evidence", enabled=False)
    calls = _wire_model(
        monkeypatch, {"slide_review": {"verdict": "pass", "issues": [], "strengths": []}}
    )
    deck = _deck(slides=[{"title": "Only", "bullets": ["An uncited claim."]}])

    review = agents.run_slide_review(deck, council_roles=roles)

    codes = {item.get("code") for item in review["issues"]}
    assert "missing_citation" not in codes
    assert [item["role"] for item in review["messages"]] == [
        "curriculum",
        "design",
        "chair",
    ]
    assert review["roles"] == ["curriculum", "design", "chair"]
    assert [task for task, _payload in calls] == ["slide_review"]


def test_a_custom_material_role_adds_findings_and_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _with_custom("material")
    calls = _wire_model(
        monkeypatch,
        {
            "council_review": {
                "issues": [
                    {
                        "severity": "high",
                        "issue": "The deck never discusses who is accountable.",
                        "fix": "Add an accountability slide.",
                    }
                ]
            },
            "slide_review": {"verdict": "pass", "issues": [], "strengths": []},
        },
    )

    review = agents.run_slide_review(_deck(), council_roles=roles)

    ethics = [item for item in review["issues"] if item.get("reviewer") == "ethics"]
    assert len(ethics) == 1
    assert ethics[0]["code"] == "role_ethics"
    assert [item["role"] for item in review["messages"]] == [
        "curriculum",
        "evidence",
        "design",
        "ethics",
        "chair",
    ]
    custom_call = next(payload for task, payload in calls if task == "council_review")
    assert custom_call["reviewer"] == "ethics"
    assert custom_call["prompt_override"] == "Review as ethics."


def test_the_material_chair_uses_its_prompt_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("material")
    _set(roles, "chair", persona_prompt="Chair voice: be brief.", model="chair-model")
    calls = _wire_model(
        monkeypatch, {"slide_review": {"verdict": "pass", "issues": [], "strengths": []}}
    )

    agents.run_slide_review(_deck(), council_roles=roles)

    chair_call = next(payload for task, payload in calls if task == "slide_review")
    assert chair_call["prompt_override"] == "Chair voice: be brief."
    assert chair_call["model"] == "chair-model"


def test_a_disabled_material_chair_skips_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = _roles("material")
    _set(roles, "chair", enabled=False)
    calls = _wire_model(
        monkeypatch, {"slide_review": {"verdict": "pass", "issues": [], "strengths": []}}
    )

    review = agents.run_slide_review(_deck(), council_roles=roles)

    assert [task for task, _payload in calls] == []
    assert review["degraded"] is False
    assert review["verdict"] == "pass"


# --- assignment ------------------------------------------------------------


def test_a_disabled_assignment_reviewer_drops_checks_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("assignment")
    _set(roles, "brief", enabled=False)
    _wire_model(monkeypatch, {"assignment_review": {"verdict": "pass", "strengths": []}})
    document = _document(overview=[], report_sections=[])

    review = assignment_council.run_assignment_council(
        document,
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
        council_roles=roles,
    )

    assert not any(item.get("reviewer") == "brief" for item in review["issues"])
    assert [item["role"] for item in review["messages"]] == ["alignment", "rubric", "chair"]
    assert review["roles"] == ["alignment", "rubric", "chair"]


def test_a_custom_assignment_role_adds_role_issues_and_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _with_custom("assignment")
    calls = _wire_model(
        monkeypatch,
        {
            "council_review": {
                "issues": [
                    {
                        "severity": "high",
                        "issue": "The brief has no ethics section.",
                        "fix": "Add the ethics section.",
                    }
                ]
            },
            "assignment_review": {"verdict": "pass", "strengths": []},
        },
    )

    review = assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
        council_roles=roles,
    )

    ethics = [item for item in review["role_issues"] if item.get("reviewer") == "ethics"]
    assert len(ethics) == 1
    assert ethics[0]["code"] == "role_ethics"
    assert any(item.get("reviewer") == "ethics" for item in review["issues"])
    assert [item["role"] for item in review["messages"]] == [
        "alignment",
        "brief",
        "rubric",
        "ethics",
        "chair",
    ]
    custom_call = next(payload for task, payload in calls if task == "council_review")
    assert custom_call["prompt_override"] == "Review as ethics."


def test_the_assignment_chair_uses_its_prompt_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("assignment")
    _set(roles, "chair", persona_prompt="Chair voice: be brief.", model="chair-model")
    calls = _wire_model(monkeypatch, {"assignment_review": {"verdict": "pass", "strengths": []}})

    assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
        council_roles=roles,
    )

    chair_call = next(payload for task, payload in calls if task == "assignment_review")
    assert chair_call["prompt_override"] == "Chair voice: be brief."
    assert chair_call["model"] == "chair-model"


# --- llm.complete ----------------------------------------------------------


def _wire_generate(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    def fake_generate(
        provider: str, model: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> SimpleNamespace:
        seen.update(provider=provider, model=model, system=messages[0]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)
    monkeypatch.setattr(llm, "key_configured", lambda provider: True)

    def route(key: str) -> dict[str, str]:
        seen["route"] = key
        return {"provider": "openai", "model": "route-model"}

    monkeypatch.setattr(llm, "agent_route", route)


def test_prompt_override_wins_and_council_review_routes_to_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    _wire_generate(monkeypatch, seen)

    result = llm.complete(
        "council_review",
        {"prompt_override": "Review as the ethics reviewer.", "model": "payload-model"},
    )

    assert result == {"ok": True}
    assert seen["route"] == "chat"
    assert "Review as the ethics reviewer." in seen["system"]
    assert DEFAULT_PROMPTS["chat"] not in seen["system"]
    assert "payload-model" in seen["model"]


def test_the_route_model_is_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _wire_generate(monkeypatch, seen)

    llm.complete("council_review", {"prompt_override": "Review as ethics."})

    assert "route-model" in seen["model"]


def test_an_unsafe_prompt_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _wire_generate(monkeypatch, seen)

    llm.complete("council_review", {"prompt_override": "Student: Sara Maktoum wrote this."})

    assert "Sara Maktoum" not in seen["system"]
    assert DEFAULT_PROMPTS["chat"] in seen["system"]


# --- the admin API ---------------------------------------------------------


def _api_user(admin: bool) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_app_admin=admin)


def _override(admin: bool, db: Any, org_id: uuid.UUID) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _api_user(admin)
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)


def _council_paths() -> tuple[str, str, str]:
    base = f"{settings.API_V1_STR}/profassist/admin/councils"
    return base, f"{base}/material", f"{base}/material/reset"


@pytest.mark.anyio
async def test_council_admin_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    base, _single, _reset = _council_paths()
    assert base in paths
    assert f"{base}/{{key}}" in paths
    assert f"{base}/{{key}}/reset" in paths


@pytest.mark.anyio
async def test_council_admin_requires_an_app_admin(client) -> None:
    _override(False, _Session(), uuid.uuid4())
    base, single, reset = _council_paths()

    listing = await client.get(base)
    saving = await client.put(single, json={"roles": default_roles("material")})
    resetting = await client.post(reset)

    assert listing.status_code == 403, listing.text
    assert saving.status_code == 403, saving.text
    assert resetting.status_code == 403, resetting.text


@pytest.mark.anyio
async def test_an_admin_lists_saves_and_resets_a_council(client) -> None:
    org_id = uuid.uuid4()
    db = _Session()
    _override(True, db, org_id)
    base, single, reset = _council_paths()

    listing = await client.get(base)
    assert listing.status_code == 200, listing.text
    assert [council["key"] for council in listing.json()["councils"]] == list(COUNCIL_KEYS)

    saved = await client.put(single, json={"roles": default_roles("material")})
    assert saved.status_code == 200, saved.text
    assert saved.json()["roles"][-1]["role_key"] == "chair"
    assert len(db.rows) == 5

    resetting = await client.post(reset)
    assert resetting.status_code == 200, resetting.text
    assert db.rows == []
    assert resetting.json()["roles"][-1]["role_key"] == "chair"


# --- grading ---------------------------------------------------------------


def _run_grading(
    monkeypatch: pytest.MonkeyPatch,
    *,
    personas: list[str] | None = None,
    persona_config: dict[str, dict[str, Any]] | None = None,
    levels: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    chosen_levels = levels or {}

    def fake_invoke(graph: Any, state: dict[str, Any], **kwargs: Any) -> tuple[Any, None]:
        return graph.invoke(state), None

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((task, payload))
        if task == "feedback":
            return {"feedback": "Keep going."}
        persona = str(payload.get("persona") or "evidence")
        return {
            "persona": persona,
            "level": chosen_levels.get(persona, "proficient"),
            "quotes": ["The report names the audience."],
            "why": "It says so.",
        }

    monkeypatch.setattr(agents, "invoke_graph", fake_invoke)
    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(
        agents, "debate_settings", lambda: {"enabled": True, "threshold": 0, "max_rounds": 1}
    )
    result = agents.run_grading_council(
        "The report names the audience.",
        {"name": "Architecture", "levels": dict(LEVELS)},
        "Short sentences.",
        personas=personas,
        persona_config=persona_config,
    )
    return result, calls


def test_grading_graph_only_adds_the_enabled_persona_nodes_and_edges() -> None:
    graph = agents.build_grading_graph(personas=["evidence", "supportive"])
    drawable = graph.get_graph()
    nodes = set(drawable.nodes)
    edges = {(edge.source, edge.target) for edge in drawable.edges}

    assert "evidence" in nodes
    assert "supportive" in nodes
    assert "strict" not in nodes
    assert ("evidence", "supportive") in edges
    assert ("supportive", "debate") in edges
    assert ("strict", "debate") not in edges
    assert ("debate", "judge") in edges
    assert ("judge", "feedback") in edges


def test_grading_graph_with_no_personas_is_a_400() -> None:
    with pytest.raises(ProfassistError) as caught:
        agents.build_grading_graph(personas=[])

    assert caught.value.status == 400
    assert caught.value.detail == "Enable at least one grading persona in Council Settings."


def test_a_persona_uses_its_council_prompt_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "evidence": {"prompt_override": "Evidence voice.", "model": "evidence-model"},
        "strict": {"prompt_override": "Strict voice.", "model": "strict-model"},
        "supportive": {"prompt_override": "", "model": ""},
    }

    _result, calls = _run_grading(monkeypatch, persona_config=config)

    persona_calls = {
        str(payload["persona"]): payload for task, payload in calls if task == "grade_persona"
    }
    assert persona_calls["evidence"]["prompt_override"] == "Evidence voice."
    assert persona_calls["evidence"]["model"] == "evidence-model"
    assert persona_calls["strict"]["prompt_override"] == "Strict voice."
    assert persona_calls["strict"]["model"] == "strict-model"
    # An empty config keeps the default route and does not invent an override.
    assert "prompt_override" not in persona_calls["supportive"]
    assert persona_calls["supportive"]["model"]


def test_a_disabled_persona_never_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, calls = _run_grading(monkeypatch, personas=["evidence", "supportive"])

    assert {payload["persona"] for task, payload in calls if task == "grade_persona"} == {
        "evidence",
        "supportive",
    }
    assert "strict" not in {
        payload["persona"] for task, payload in calls if task == "grade_persona"
    }


def test_debate_reuses_the_persona_prompt_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "evidence": {"prompt_override": "Evidence voice.", "model": "evidence-model"},
        "strict": {"prompt_override": "Strict voice.", "model": "strict-model"},
        "supportive": {"prompt_override": "Supportive voice.", "model": "supportive-model"},
    }
    levels = {"evidence": "advanced", "strict": "beginning", "supportive": "proficient"}

    result, calls = _run_grading(monkeypatch, persona_config=config, levels=levels)

    revised = {
        str(payload["persona"]): payload for task, payload in calls if task == "grade_revise"
    }
    assert revised["evidence"]["prompt_override"] == "Evidence voice."
    assert revised["evidence"]["model"] == "evidence-model"
    assert revised["strict"]["prompt_override"] == "Strict voice."
    assert revised["strict"]["model"] == "strict-model"
    assert revised["supportive"]["prompt_override"] == "Supportive voice."
    assert revised["supportive"]["model"] == "supportive-model"
    # The judge and the feedback step still run after the debate.
    assert result["judge"]["evidence_status"] == "ok"
    assert result["feedback"] == "Keep going."
    assert [task for task, _payload in calls].count("feedback") == 1


def test_debate_is_skipped_when_the_council_agrees(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _run_grading(monkeypatch, levels={})

    assert not [task for task, _payload in calls if task == "grade_revise"]
    assert result["debate_rounds"] == []
    assert result["judge"]["evidence_status"] == "ok"


# --- outline ---------------------------------------------------------------


class _ReviewSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, statement: Any) -> _Result:
        return _Result([], count=0)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1


def _outline_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        body={
            "clos": [{"code": "LO1", "text": "Understand things", "plos": []}],
            "plos": [{"code": "PLO1", "text": "Apply the discipline."}],
            "tasks": [{"number": "A1", "weight": 50, "lo_codes": []}],
            "readings": ["A 2010 book."],
        },
        instructions="",
    )


def _wire_outline(
    monkeypatch: pytest.MonkeyPatch,
    roles: list[dict[str, Any]],
    *,
    tool: Any | None = None,
    replies: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[uuid.UUID, str]]]:
    row = _outline_row()
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_roles: list[tuple[uuid.UUID, str]] = []

    async def fake_get_outline(*args: Any) -> Any:
        return row

    async def fake_load_roles(db: Any, org_id: uuid.UUID, key: str) -> list[dict[str, Any]]:
        seen_roles.append((org_id, key))
        return roles

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((task, payload))
        reply = (replies or {}).get(task)
        if callable(reply):
            return reply(payload)
        return reply if isinstance(reply, dict) else {"summary": "Reviewed."}

    monkeypatch.setattr(outline_review, "get_outline", fake_get_outline)
    monkeypatch.setattr(outline_review, "load_council_roles", fake_load_roles)
    monkeypatch.setattr(llm, "complete", fake_complete)
    if tool is not None:
        monkeypatch.setattr(outline_review, "tool_enabled", tool)
    return calls, seen_roles


@pytest.mark.anyio
async def test_outline_reviewers_are_enabled_roles_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("outline")
    _set(roles, "balance", enabled=False)
    seen_tools: list[str] = []

    def fake_tool(agent: str, tool: str) -> bool:
        seen_tools.append(tool)
        return tool != "debate"

    calls, seen_roles = _wire_outline(monkeypatch, roles, tool=fake_tool)
    org_id = uuid.uuid4()

    result = await outline_review.run_review(
        _ReviewSession(), org_id, uuid.uuid4(), uuid.uuid4(), mode="council", reviewer="curriculum"
    )

    assert seen_roles == [(org_id, "outline")]
    assert [tool for tool in seen_tools if tool != "debate"] == [
        "curriculum",
        "alignment",
        "student",
    ]
    reviewers = {item["reviewer"] for item in result["findings"]}
    assert "balance" not in reviewers
    assert reviewers <= {"curriculum", "alignment", "student"}
    assert [task for task, _payload in calls] == ["outline_review"]


@pytest.mark.anyio
async def test_the_outline_chair_uses_its_prompt_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = _roles("outline")
    _set(roles, "chair", persona_prompt="Chair voice: be brief.", model="chair-model")
    calls, _seen_roles = _wire_outline(monkeypatch, roles)

    await outline_review.run_review(
        _ReviewSession(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        mode="single",
        reviewer="curriculum",
    )

    chair_call = next(payload for task, payload in calls if task == "outline_review")
    assert chair_call["prompt_override"] == "Chair voice: be brief."
    assert chair_call["model"] == "chair-model"


@pytest.mark.anyio
async def test_a_custom_outline_reviewer_adds_findings_the_chair_sees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _with_custom("outline")
    _set(roles, "ethics", model="ethics-model")
    calls, _seen_roles = _wire_outline(
        monkeypatch,
        roles,
        replies={
            "council_review": {
                "issues": [
                    {
                        "severity": "high",
                        "section": "policies",
                        "object_id": "ethics",
                        "issue": "The outline has no research ethics policy.",
                        "fix": "Add a research ethics section.",
                    }
                ]
            }
        },
    )

    result = await outline_review.run_review(
        _ReviewSession(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        mode="council",
        reviewer="curriculum",
    )

    custom_call = next(payload for task, payload in calls if task == "council_review")
    assert custom_call["prompt_override"] == "Review as ethics."
    assert custom_call["model"] == "ethics-model"

    ethics = [item for item in result["findings"] if item["reviewer"] == "ethics"]
    assert len(ethics) == 1
    assert ethics[0]["severity"] == "high"
    assert ethics[0]["message"] == "The outline has no research ethics policy."
    assert ethics[0]["fix"] == {"note": "Add a research ethics section."}
    assert ethics[0]["applied"] is False
    assert result["findings"][-1]["reviewer"] == "ethics"

    chair_call = next(payload for task, payload in calls if task == "outline_review")
    assert any(item["reviewer"] == "ethics" for item in chair_call["findings"])


@pytest.mark.anyio
async def test_a_disabled_custom_outline_reviewer_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _with_custom("outline")
    _set(roles, "ethics", enabled=False)
    calls, _seen_roles = _wire_outline(monkeypatch, roles)

    result = await outline_review.run_review(
        _ReviewSession(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        mode="council",
        reviewer="curriculum",
    )

    assert [task for task, _payload in calls] == ["outline_review"]
    assert all(item["reviewer"] != "ethics" for item in result["findings"])


@pytest.mark.anyio
async def test_no_enabled_outline_reviewer_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = _roles("outline")
    for role in roles:
        if role["kind"] == "deterministic":
            role["enabled"] = False
    calls, _seen_roles = _wire_outline(monkeypatch, roles)

    with pytest.raises(ProfassistError) as caught:
        await outline_review.run_review(
            _ReviewSession(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            mode="council",
            reviewer="curriculum",
        )

    assert caught.value.status == 400
    assert calls == []


# --- config scoping --------------------------------------------------------


@pytest.mark.anyio
async def test_grading_and_outline_roles_load_for_the_requesting_org() -> None:
    mine, other = uuid.uuid4(), uuid.uuid4()
    rows = [_saved(mine, "grading", role) for role in _roles("grading")]
    db = _Session(rows)

    loaded = await load_council_roles(db, mine, "grading")
    theirs = await load_council_roles(db, other, "grading")

    assert [role["role_key"] for role in loaded] == [
        "evidence",
        "strict",
        "supportive",
        "chair",
    ]
    # Another university never sees these rows; it falls back to the code default.
    assert [role["role_key"] for role in theirs] == [
        "evidence",
        "strict",
        "supportive",
        "chair",
    ]
