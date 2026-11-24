"""The chat and MCP tool catalog: routing, model choice, and the MCP limit."""

import uuid

import pytest

NEW_TOOLS = {
    "list_students",
    "create_groups",
    "list_groups",
    "list_assignments",
    "generate_materials",
    "list_decks",
    "grade_queue",
    "approve_draft",
    "publish_outline",
    "generate_outline",
    "refine_outline",
}


def test_tool_catalog_lists_the_new_platform_tools() -> None:
    from app.profassist.platform_tools import tool_catalog

    catalog = {row["name"]: row for row in tool_catalog()}
    assert set(catalog) >= NEW_TOOLS
    for name in ("create_groups", "approve_draft", "publish_outline", "generate_outline"):
        assert catalog[name]["confirm"] is True
    for name in ("list_students", "list_groups", "list_assignments", "generate_materials"):
        assert catalog[name]["confirm"] is False


@pytest.mark.parametrize(
    "message,expected",
    [
        ("show me the students", "list_students"),
        ("who is on the roster?", "list_students"),
        ("how many attendees are there", "list_students"),
        ("create groups for this course", "create_groups"),
        ("form 3 groups", "create_groups"),
        ("list groups", "list_groups"),
        ("who is in group A?", "list_groups"),
        ("list assignments in the course", "list_assignments"),
        ("show assignments in MAAI 903", "list_assignments"),
        ("make slides for week 4", "generate_materials"),
        ("build a deck for week 2", "generate_materials"),
        ("list decks", "list_decks"),
        ("show my presentations", "list_decks"),
        ("show the grade queue", "grade_queue"),
        ("what are the results?", "grade_queue"),
        ("approve grade", "approve_draft"),
        ("publish outline", "publish_outline"),
        ("generate the full outline", "generate_outline"),
        ("refine the outline", "refine_outline"),
    ],
)
def test_choose_tool_routes_the_new_phrases(message: str, expected: str) -> None:
    from app.profassist.platform_tools import choose_tool

    assert choose_tool(message)[0] == expected


def test_choose_tool_parses_week_and_group_count() -> None:
    from app.profassist.platform_tools import choose_tool

    name, args = choose_tool("make slides for week 4")
    assert name == "generate_materials"
    assert args["week"] == 4

    name, args = choose_tool("form 3 groups")
    assert name == "create_groups"
    assert len(args["groups"]) == 3
    assert args["groups"][0]["name"] == "Group 1"


def test_choose_tool_uses_outline_context_for_outline_mutations() -> None:
    from app.profassist.platform_tools import choose_tool

    oid = "11111111-1111-1111-1111-111111111111"
    name, args = choose_tool("publish this outline", {"outline_id": oid})
    assert name == "publish_outline"
    assert args["outline_id"] == oid

    name, args = choose_tool("generate the full outline", {"outline_id": oid})
    assert name == "generate_outline"
    assert args["outline_id"] == oid

    name, args = choose_tool("refine the outline", {"outline_id": oid})
    assert name == "refine_outline"
    assert args["outline_id"] == oid


def test_choose_tool_keeps_the_existing_fallbacks() -> None:
    from app.profassist.platform_tools import choose_tool

    assert choose_tool("Please sync Moodle")[0] == "moodle_sync"
    assert choose_tool("Suggest an assessment for LO1")[0] == "suggest_assessments"
    assert choose_tool("hello", {})[0] == "assistant_chat"


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content: str, tool_calls: list[_ToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, content: str, tool_calls: list[_ToolCall] | None = None) -> None:
        self.message = _Message(content, tool_calls)


class _Response:
    def __init__(self, content: str, tool_calls: list[_ToolCall] | None = None) -> None:
        self.choices = [_Choice(content, tool_calls)]


def _patch_provider(monkeypatch: pytest.MonkeyPatch, content: str) -> dict:
    import app.profassist.providers as providers

    calls: dict = {}

    def fake_generate(provider, model, messages, **kwargs):
        calls.update(provider=provider, model=model, messages=messages)
        return _Response(content)

    monkeypatch.setattr(providers, "key_configured", lambda provider: provider == "openai")
    monkeypatch.setattr(providers, "generate", fake_generate)
    return calls


def _fake_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.profassist.settings_admin as settings_admin

    async def fake_load_runtime(db, org_id, user_id):
        return None

    monkeypatch.setattr(settings_admin, "load_runtime", fake_load_runtime)


def test_model_chooser_returns_a_listed_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.platform_tools import choose_tool_with_model

    calls = _patch_provider(monkeypatch, '{"tool": "list_students", "arguments": {}}')
    choice = choose_tool_with_model("who is here?", {})

    assert choice == ("list_students", {})
    listing = calls["messages"][0]["content"]
    assert "list_students" in listing
    assert "admin_ai_settings" not in listing


def test_model_chooser_refuses_admin_tools_without_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.platform_tools import choose_tool_with_model

    _patch_provider(monkeypatch, '{"tool": "admin_ai_settings", "arguments": {}}')
    assert choose_tool_with_model("show settings", {"is_admin": False}) is None
    assert choose_tool_with_model("show settings", {"is_admin": True}) == (
        "admin_ai_settings",
        {},
    )


@pytest.mark.parametrize(
    "content",
    ["not json at all", '{"tool": "made_up_tool", "arguments": {}}', '["list_students"]'],
)
def test_model_chooser_returns_none_for_bad_answers(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    from app.profassist.platform_tools import choose_tool_with_model

    _patch_provider(monkeypatch, content)
    assert choose_tool_with_model("who is here?", {}) is None


def test_tool_schemas_cover_every_tool() -> None:
    from app.profassist.platform_tools import (
        TOOL_SCHEMAS,
        TOOL_SPECS,
        openai_tool_definitions,
        tool_catalog,
    )

    names = {spec["name"] for spec in TOOL_SPECS}
    assert len(names) == 31
    assert set(TOOL_SCHEMAS) == names
    for row in tool_catalog():
        assert row["parameters"] is TOOL_SCHEMAS[row["name"]]
        assert row["parameters"]["type"] == "object"
        assert row["parameters"]["additionalProperties"] is True

    professor_tools = {item["function"]["name"] for item in openai_tool_definitions(is_admin=False)}
    assert len(professor_tools) == 30
    assert "admin_ai_settings" not in professor_tools
    admin_tools = {item["function"]["name"] for item in openai_tool_definitions(is_admin=True)}
    assert admin_tools == names


def _patch_native(monkeypatch: pytest.MonkeyPatch, responses: list[_Response]) -> list[dict]:
    import app.profassist.providers as providers

    script = iter(responses)
    calls: list[dict] = []

    def fake_generate(provider, model, messages, **kwargs):
        calls.append({"provider": provider, "model": model, "messages": messages, **kwargs})
        return next(script)

    monkeypatch.setattr(providers, "key_configured", lambda provider: True)
    monkeypatch.setattr(providers, "generate", fake_generate)
    return calls


def _patch_observe(monkeypatch: pytest.MonkeyPatch, url: str | None = None) -> list[dict]:
    """Spy on invoke_graph, still run the real graph, and hand back a trace URL."""
    import app.profassist.platform_tools as tools

    calls: list[dict] = []

    def fake_invoke_graph(graph, state, *, name, metadata=None):
        calls.append({"graph": graph, "state": state, "name": name, "metadata": metadata})
        return graph.invoke(state), url

    monkeypatch.setattr(tools, "invoke_graph", fake_invoke_graph)
    return calls


def _forbid_keyword_chooser(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.profassist.platform_tools as tools

    def refuse(*_args, **_kwargs):
        raise AssertionError("chat_turn must not use the keyword chooser")

    monkeypatch.setattr(tools, "choose_tool", refuse)
    monkeypatch.setattr(tools, "choose_tool_with_model", refuse)


def test_chat_turn_uses_native_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.platform_tools as tools

    _fake_runtime(monkeypatch)
    _forbid_keyword_chooser(monkeypatch)
    trace_url = "http://localhost:3100/project/profassist-project/traces/abc"
    traced = _patch_observe(monkeypatch, trace_url)
    calls = _patch_native(
        monkeypatch,
        [
            _Response("", [_ToolCall("call_1", "list_students", '{"code": "MAAI903"}')]),
            _Response("The roster is empty."),
        ],
    )
    seen: dict = {}

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        seen.update(name=name, arguments=arguments, confirmed=confirmed)
        return {
            "tool": name,
            "result": {"course": "MAAI903", "students": []},
            "needs_confirm": False,
        }

    monkeypatch.setattr(tools, "invoke_tool", fake_invoke)

    result = asyncio.run(
        tools.chat_turn(
            None,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            message="who is in MAAI 903?",
        )
    )

    assert seen["name"] == "list_students"
    assert seen["arguments"] == {"code": "MAAI903"}
    assert seen["confirmed"] is False
    assert result["reply"] == "The roster is empty."
    assert result["tool"] == "list_students"
    assert result["arguments"] == {"code": "MAAI903"}
    assert result["trace_url"] == trace_url
    assert calls[0]["tool_choice"] == "auto"
    assert any(item["function"]["name"] == "list_students" for item in calls[0]["tools"])
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert calls[1]["messages"][-1]["tool_call_id"] == "call_1"

    assert len(traced) == 1
    assert traced[0]["name"] == "professor-chat"
    assert traced[0]["metadata"] == {"kind": "chat"}
    assert {"model", "tools"} <= set(traced[0]["graph"].get_graph().nodes)
    assert traced[0]["state"]["rounds"] == 0
    assert traced[0]["state"]["needs_confirm"] is False


def test_chat_turn_asks_to_confirm_a_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.platform_tools as tools

    _fake_runtime(monkeypatch)
    _forbid_keyword_chooser(monkeypatch)
    _patch_observe(monkeypatch)
    _patch_native(
        monkeypatch,
        [_Response("", [_ToolCall("call_1", "create_groups", '{"code": "MAAI903"}')])],
    )

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        assert confirmed is False
        return {
            "tool": name,
            "needs_confirm": True,
            "preview": "Replace a course's student groups with the groups you name.",
            "confirm_with": "confirm",
        }

    monkeypatch.setattr(tools, "invoke_tool", fake_invoke)

    result = asyncio.run(
        tools.chat_turn(
            None,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            message="create groups",
        )
    )

    assert result["needs_confirm"] is True
    assert result["tool"] == "create_groups"
    assert "Reply confirm" in result["reply"]


def test_chat_turn_honours_an_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.platform_tools as tools

    _fake_runtime(monkeypatch)
    _forbid_keyword_chooser(monkeypatch)
    traced = _patch_observe(monkeypatch)
    _patch_native(monkeypatch, [_Response("The groups are saved.")])
    seen: dict = {}

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        seen.update(name=name, confirmed=confirmed)
        return {"tool": name, "result": {"groups": []}, "needs_confirm": False}

    monkeypatch.setattr(tools, "invoke_tool", fake_invoke)

    result = asyncio.run(
        tools.chat_turn(
            None,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            message="create groups",
            confirmed=True,
            pending_tool="create_groups",
        )
    )

    assert seen == {"name": "create_groups", "confirmed": True}
    assert result["reply"].startswith("Saved 0 groups")
    assert traced == []


def test_chat_turn_stops_after_four_tool_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.platform_tools as tools

    _fake_runtime(monkeypatch)
    _forbid_keyword_chooser(monkeypatch)
    _patch_observe(monkeypatch)
    calls = _patch_native(
        monkeypatch,
        [_Response("", [_ToolCall(f"call_{index}", "list_students", "{}")]) for index in range(4)],
    )
    runs = {"count": 0}

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        runs["count"] += 1
        return {
            "tool": name,
            "result": {"course": "MAAI903", "students": []},
            "needs_confirm": False,
        }

    monkeypatch.setattr(tools, "invoke_tool", fake_invoke)

    result = asyncio.run(
        tools.chat_turn(
            None,
            uuid.uuid4(),
            uuid.uuid4(),
            is_admin=False,
            message="keep listing students",
        )
    )

    assert len(calls) == 4
    assert runs["count"] == 4
    assert result["needs_confirm"] is False
    assert result["tool"] == "list_students"
    assert result["reply"] == "No students are on the MAAI903 roster yet."
    assert "trace_url" not in result


def test_chat_turn_returns_503_without_a_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.platform_tools as tools
    import app.profassist.providers as providers
    from app.profassist.errors import ProfassistError

    _fake_runtime(monkeypatch)
    traced = _patch_observe(monkeypatch)
    monkeypatch.setattr(providers, "key_configured", lambda provider: False)

    with pytest.raises(ProfassistError) as raised:
        asyncio.run(
            tools.chat_turn(
                None,
                uuid.uuid4(),
                uuid.uuid4(),
                is_admin=False,
                message="hello",
            )
        )
    assert raised.value.status == 503
    assert "No AI model is configured" in raised.value.detail
    assert traced == []
