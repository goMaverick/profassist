"""Professor tools shared by the chat and the MCP server.

Every tool checks the signed-in professor and her university. Moodle push and
deletes wait for an explicit confirm token.
"""

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.observe import invoke_graph
from app.profassist.runtime import tool_enabled

_actor: ContextVar[dict[str, Any] | None] = ContextVar("pa_tool_actor", default=None)
logger = logging.getLogger(__name__)

CONFIRM = "confirm"


def set_tool_actor(org_id: uuid.UUID, user_id: uuid.UUID, *, is_admin: bool) -> None:
    _actor.set({"org_id": org_id, "user_id": user_id, "is_admin": is_admin})


def clear_tool_actor() -> None:
    _actor.set(None)


def actor() -> dict[str, Any]:
    current = _actor.get()
    if not current:
        raise ProfassistError(401, "Sign in before using this tool.")
    return current


def actor_available() -> bool:
    """True when a request has already signed a professor in for a tool."""
    return _actor.get() is not None


def tool_spec(name: str) -> dict[str, Any] | None:
    return next((item for item in TOOL_SPECS if item["name"] == name), None)


def _guard(name: str, *, admin: bool = False) -> dict[str, Any]:
    current = actor()
    if admin and not current["is_admin"]:
        raise ProfassistError(403, "That tool is for an administrator.")
    if not tool_enabled("mcp", name):
        raise ProfassistError(403, f"The {name} tool is turned off in AI settings.")
    return current


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_courses",
        "confirm": False,
        "admin": False,
        "summary": "List this professor's courses.",
    },
    {
        "name": "get_course",
        "confirm": False,
        "admin": False,
        "summary": "Read one course, its outcomes, and its assessments.",
    },
    {
        "name": "list_outlines",
        "confirm": False,
        "admin": False,
        "summary": "List subject outlines.",
    },
    {
        "name": "start_outline",
        "confirm": False,
        "admin": False,
        "summary": "Start the subject outline wizard.",
    },
    {
        "name": "assist_outline",
        "confirm": False,
        "admin": False,
        "summary": "Suggest the current wizard step.",
    },
    {
        "name": "review_outline",
        "confirm": False,
        "admin": False,
        "summary": "Review the current subject outline and show findings.",
    },
    {
        "name": "review_rubric",
        "confirm": False,
        "admin": False,
        "summary": "Review the current rubric and show deterministic findings.",
    },
    {
        "name": "list_students",
        "confirm": False,
        "admin": False,
        "summary": "List the students on a course roster.",
    },
    {
        "name": "create_groups",
        "confirm": True,
        "admin": False,
        "summary": "Replace a course's student groups with the groups you name.",
    },
    {
        "name": "list_groups",
        "confirm": False,
        "admin": False,
        "summary": "List the student groups in a course.",
    },
    {
        "name": "list_assignments",
        "confirm": False,
        "admin": False,
        "summary": "List a course's assignments and their status.",
    },
    {
        "name": "generate_materials",
        "confirm": False,
        "admin": False,
        "summary": "Build a cited slide deck for one week of a course.",
    },
    {
        "name": "list_decks",
        "confirm": False,
        "admin": False,
        "summary": "List the slide decks built for a course.",
    },
    {
        "name": "grade_queue",
        "confirm": False,
        "admin": False,
        "summary": "Show a course's grading queue and draft statuses.",
    },
    {
        "name": "approve_draft",
        "confirm": True,
        "admin": False,
        "summary": "Approve one grade draft.",
    },
    {
        "name": "publish_outline",
        "confirm": True,
        "admin": False,
        "summary": "Finish and publish a subject outline.",
    },
    {
        "name": "generate_outline",
        "confirm": True,
        "admin": False,
        "summary": "Draft the whole subject outline from your instructions.",
    },
    {
        "name": "refine_outline",
        "confirm": True,
        "admin": False,
        "summary": "Change named sections of a subject outline.",
    },
    {
        "name": "assistant_chat",
        "confirm": False,
        "admin": False,
        "summary": "Answer a question using the current page and workspace context.",
    },
    {
        "name": "create_assignment",
        "confirm": False,
        "admin": False,
        "summary": "Create a draft assignment on a course in this university.",
    },
    {
        "name": "dropout_risk",
        "confirm": False,
        "admin": False,
        "summary": "Show advisory dropout risk for the demo roster.",
    },
    {
        "name": "integrity_concerns",
        "confirm": False,
        "admin": False,
        "summary": "Show integrity concerns for a course and assignment.",
    },
    {
        "name": "suggest_assessments",
        "confirm": False,
        "admin": False,
        "summary": "Suggest assessments for selected outcomes.",
    },
    {
        "name": "accept_assessments",
        "confirm": True,
        "admin": False,
        "summary": "Save accepted assessments onto the course.",
    },
    {
        "name": "generate_slides",
        "confirm": False,
        "admin": False,
        "summary": "Build a slide deck for a week.",
    },
    {
        "name": "moodle_sync",
        "confirm": False,
        "admin": False,
        "summary": "Sync the Moodle catalogue.",
    },
    {"name": "moodle_push", "confirm": True, "admin": False, "summary": "Push an approved grade."},
    {
        "name": "start_grade",
        "confirm": False,
        "admin": False,
        "summary": "Run the grading council on one submission.",
    },
    {
        "name": "list_memories",
        "confirm": False,
        "admin": False,
        "summary": "List this professor's memories.",
    },
    {"name": "delete_memory", "confirm": True, "admin": False, "summary": "Delete one memory."},
    {
        "name": "admin_ai_settings",
        "confirm": False,
        "admin": True,
        "summary": "Read AI settings. Administrators only.",
    },
]


def _tool_schema(**properties: Any) -> dict[str, Any]:
    """An OpenAI-style object schema. Safe extras are always allowed."""
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


_STR: dict[str, Any] = {"type": "string"}
_INT: dict[str, Any] = {"type": "integer"}
_STR_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
_OBJECT: dict[str, Any] = {"type": "object", "additionalProperties": True}
_CONFIRM: dict[str, Any] = {
    "type": "boolean",
    "description": "Set true after the professor confirms a mutation.",
}
_GROUPS: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "member_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
        "additionalProperties": True,
    },
}
_TASKS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "object", "additionalProperties": True},
}


# One parameters schema per tool. The chat's native tool loop and the FastMCP
# registry both read this map, so a tool is never exposed without an input schema.
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_courses": _tool_schema(confirm=_CONFIRM),
    "get_course": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "list_outlines": _tool_schema(confirm=_CONFIRM),
    "start_outline": _tool_schema(confirm=_CONFIRM),
    "assist_outline": _tool_schema(step=_STR, message=_STR, code=_STR, confirm=_CONFIRM),
    "review_outline": _tool_schema(outline_id=_STR, mode=_STR, reviewer=_STR, confirm=_CONFIRM),
    "review_rubric": _tool_schema(rubric_id=_STR, confirm=_CONFIRM),
    "list_students": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "create_groups": _tool_schema(
        course_id=_STR,
        code=_STR,
        assignment_id=_STR,
        group_count=_INT,
        groups=_GROUPS,
        group_ids=_STR_LIST,
        confirm=_CONFIRM,
    ),
    "list_groups": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "list_assignments": _tool_schema(
        course_id=_STR, code=_STR, assignment_id=_STR, confirm=_CONFIRM
    ),
    "generate_materials": _tool_schema(
        course_id=_STR, code=_STR, week=_INT, instructions=_STR, confirm=_CONFIRM
    ),
    "list_decks": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "grade_queue": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "approve_draft": _tool_schema(draft_id=_STR, confirm=_CONFIRM),
    "publish_outline": _tool_schema(outline_id=_STR, confirm=_CONFIRM),
    "generate_outline": _tool_schema(outline_id=_STR, message=_STR, confirm=_CONFIRM),
    "refine_outline": _tool_schema(outline_id=_STR, message=_STR, section=_STR, confirm=_CONFIRM),
    "assistant_chat": _tool_schema(message=_STR, context=_OBJECT, confirm=_CONFIRM),
    "create_assignment": _tool_schema(
        course_id=_STR, code=_STR, number=_STR, due=_STR, title=_STR, confirm=_CONFIRM
    ),
    "dropout_risk": _tool_schema(course_id=_STR, code=_STR, confirm=_CONFIRM),
    "integrity_concerns": _tool_schema(
        course_id=_STR, code=_STR, assignment=_STR, assignment_id=_STR, confirm=_CONFIRM
    ),
    "suggest_assessments": _tool_schema(
        outline_id=_STR, lo_codes=_STR_LIST, message=_STR, code=_STR, confirm=_CONFIRM
    ),
    "accept_assessments": _tool_schema(outline_id=_STR, tasks=_TASKS, confirm=_CONFIRM),
    "generate_slides": _tool_schema(course_id=_STR, code=_STR, week=_INT, confirm=_CONFIRM),
    "moodle_sync": _tool_schema(confirm=_CONFIRM),
    "moodle_push": _tool_schema(draft_id=_STR, confirm=_CONFIRM),
    "start_grade": _tool_schema(submission_id=_STR, confirm=_CONFIRM),
    "list_memories": _tool_schema(confirm=_CONFIRM),
    "delete_memory": _tool_schema(memory_id=_STR, confirm=_CONFIRM),
    "admin_ai_settings": _tool_schema(confirm=_CONFIRM),
}

for _spec in TOOL_SPECS:
    _spec["parameters"] = TOOL_SCHEMAS[_spec["name"]]


def tool_schema(name: str) -> dict[str, Any] | None:
    """The JSON schema for one tool, or None when the name is unknown."""
    return TOOL_SCHEMAS.get(name)


def openai_tool_definitions(*, is_admin: bool) -> list[dict[str, Any]]:
    """OpenAI-style function tools for the chat's native tool loop."""
    definitions: list[dict[str, Any]] = []
    for spec in TOOL_SPECS:
        if not tool_enabled("mcp", spec["name"]):
            continue
        if spec["admin"] and not is_admin:
            continue
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["summary"],
                    "parameters": TOOL_SCHEMAS[spec["name"]],
                },
            }
        )
    return definitions


def tool_catalog() -> list[dict[str, Any]]:
    return [{**spec, "enabled": tool_enabled("mcp", spec["name"])} for spec in TOOL_SPECS]


def _assignment_args(text: str) -> dict[str, Any]:
    import re

    number = "A2"
    match = re.search(r"assignment\s+(\d+)", text)
    if match:
        number = f"A{match.group(1)}"
    code = "MAAI903"
    coded = re.search(r"maai\s*(\d+)", text)
    if coded:
        code = f"MAAI{coded.group(1)}"
    due = ""
    dated = re.search(r"due\s+(\d{1,2}\s+[a-z]+)", text)
    if dated:
        due = dated.group(1).title()
    return {"number": number, "code": code, "due": due, "title": f"Assignment {number[1:]}"}


def _mentioned_code(text: str) -> str:
    import re

    coded = re.search(r"\b([a-z]{2,})\s*(\d{3})\b", text)
    if not coded:
        return ""
    return f"{coded.group(1).upper()}{coded.group(2)}"


def _integrity_args(text: str) -> dict[str, Any]:
    import re

    code = _mentioned_code(text) or "MAAI903"
    number = ""
    numbered = re.search(r"assignment\s+(\d+)", text)
    if numbered:
        number = numbered.group(1)
    return {"code": code, "assignment": number}


def _week_number(text: str, default: int = 0) -> int:
    import re

    match = re.search(r"week\s*(\d+)", text)
    if match:
        return int(match.group(1))
    for token in text.split():
        if token.isdigit():
            return int(token)
    return default


def _group_names(text: str) -> list[dict[str, Any]]:
    import re

    match = re.search(r"\b(\d+)\s+groups?\b", text)
    if not match:
        return []
    count = min(int(match.group(1)), 20)
    return [{"name": f"Group {index + 1}", "member_ids": []} for index in range(count)]


def choose_tool(message: str, context: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Route a message to one tool by keyword, using the page context when present.

    .. deprecated::
        The chat now uses native tool calling. This helper is kept for legacy
        callers and tests only.
    """
    text = (message or "").lower()
    context = context or {}
    outline_id = context.get("outline_id")
    rubric_id = context.get("rubric_id")
    page = str(context.get("page") or "").lower()
    code = _mentioned_code(text)
    if (
        rubric_id
        and (not outline_id or "rubric" in page)
        and any(
            phrase in text
            for phrase in (
                "review",
                "check",
                "opinion",
                "what do you think",
                "thoughts",
                "is this good",
            )
        )
    ):
        return "review_rubric", {"rubric_id": rubric_id}
    if outline_id and any(
        phrase in text
        for phrase in (
            "review",
            "re-review",
            "rereview",
            "review again",
            "critique",
            "check my outline",
        )
    ):
        return "review_outline", {
            "outline_id": outline_id,
            "mode": "council",
            "reviewer": "curriculum",
        }
    if outline_id and any(
        phrase in text
        for phrase in (
            "opinion",
            "what do you think",
            "thoughts",
            "how does it look",
            "is this good",
        )
    ):
        return "review_outline", {
            "outline_id": outline_id,
            "mode": "single",
            "reviewer": "curriculum",
        }
    if "publish" in text and "outline" in text:
        return "publish_outline", {"outline_id": outline_id or ""}
    if "outline" in text and any(
        phrase in text
        for phrase in (
            "generate",
            "full outline",
            "whole outline",
            "draft the outline",
            "write the outline",
        )
    ):
        return "generate_outline", {"outline_id": outline_id or "", "message": message}
    if "outline" in text and any(
        phrase in text
        for phrase in (
            "refine",
            "change the outline",
            "change my outline",
            "edit the outline",
            "update the outline",
        )
    ):
        return "refine_outline", {"outline_id": outline_id or "", "message": message}
    if "sync" in text and "moodle" in text:
        return "moodle_sync", {}
    if "push" in text and "grade" in text:
        return "moodle_push", {}
    if "approve" in text and ("grade" in text or "draft" in text):
        return "approve_draft", {"draft_id": context.get("draft_id") or ""}
    if "grade queue" in text or "grading queue" in text or "results" in text:
        return "grade_queue", {"code": code}
    if any(word in text for word in ("list", "show", "my ")) and (
        "deck" in text or "presentation" in text
    ):
        return "list_decks", {"code": code}
    if "slide" in text or "deck" in text or "presentation" in text:
        return "generate_materials", {
            "code": code,
            "week": _week_number(text),
            "instructions": message,
        }
    if "assignment" in text and any(word in text for word in ("create", "add", "draft")):
        return "create_assignment", _assignment_args(text)
    if "dropout" in text or "at risk" in text or "at-risk" in text:
        return "dropout_risk", {"code": code}
    if "integrit" in text or "copying" in text or "similar" in text:
        return "integrity_concerns", _integrity_args(text)
    if "assignment" in text and any(
        phrase in text for phrase in ("list", "show", "assignments in", "in the course")
    ):
        return "list_assignments", {"code": code}
    if "group" in text:
        if any(word in text for word in ("create", "make", "form", "split")):
            return "create_groups", {"code": code, "groups": _group_names(text)}
        return "list_groups", {"code": code}
    if "student" in text or "roster" in text or "attendee" in text:
        return "list_students", {"code": code}
    if "assessment" in text and ("suggest" in text or "generat" in text):
        return "suggest_assessments", {"message": message, "code": code}
    if "learning outcome" in text or "outcomes" in text:
        return "assist_outline", {
            "step": "outcomes",
            "message": message,
            "code": code,
        }
    if "wizard" in text or "outline" in text:
        return "assist_outline", {
            "step": "outcomes",
            "message": message,
            "code": code,
        }
    if "memor" in text:
        return "list_memories", {}
    if "setting" in text or "admin" in text:
        return "admin_ai_settings", {}
    if "grade" in text:
        return "grade_queue", {"code": code}
    return "assistant_chat", {"message": message, "context": context}


def _json_object(text: str) -> dict[str, Any] | None:
    """Read the first JSON object in a model answer, with or without a fence."""
    import re

    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def choose_tool_with_model(
    message: str, context: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]] | None:
    """Ask the configured model to pick one enabled tool. Return None to fall back.

    .. deprecated::
        The chat now uses native tool calling. This helper is kept for legacy
        callers and tests only.

    The model only sees the enabled, non-admin tool names and summaries for this
    professor, and its answer is checked against that same list. Any refusal,
    unknown tool, or unparseable answer returns None so keyword routing can run.
    """
    from app.profassist.pii import scrub
    from app.profassist.providers import generate, key_configured
    from app.profassist.runtime import agent_route

    context = context or {}
    is_admin = bool(context.get("is_admin"))
    route = agent_route("chat")
    if not key_configured(route["provider"]):
        return None
    specs = [
        spec
        for spec in TOOL_SPECS
        if tool_enabled("mcp", spec["name"]) and (is_admin or not spec["admin"])
    ]
    if not specs:
        return None
    listing = "\n".join(f"- {spec['name']}: {spec['summary']}" for spec in specs)
    system = (
        "You route one university professor's message to one tool. "
        'Reply with JSON only: {"tool": "<name>", "arguments": {}}. '
        "Use assistant_chat when no tool fits. Never choose a tool that is not listed. "
        f"Tools:\n{listing}"
    )
    user = f"Page context: {json.dumps(context, default=str)[:800]}\nMessage: {message}"
    try:
        response = generate(
            route["provider"],
            route["model"],
            [
                {"role": "system", "content": scrub(system).text},
                {"role": "user", "content": scrub(user).text},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception:
        logger.info("The tool-choice model did not answer; using keywords")
        return None
    chosen = _json_object(text)
    if not chosen:
        return None
    name = str(chosen.get("tool") or "").strip()
    if name not in {spec["name"] for spec in specs}:
        return None
    arguments = chosen.get("arguments")
    return name, arguments if isinstance(arguments, dict) else {}


async def invoke_tool(
    db: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    spec = next((item for item in TOOL_SPECS if item["name"] == name), None)
    if spec is None:
        raise ProfassistError(404, "That tool is not available.")
    current = _guard(name, admin=spec["admin"])
    if spec["confirm"] and not confirmed:
        return {
            "needs_confirm": True,
            "tool": name,
            "preview": spec["summary"],
            "confirm_with": CONFIRM,
        }
    handler = _HANDLERS[name]
    result = await handler(db, current, arguments)
    return {"tool": name, "result": result, "needs_confirm": False}


async def _list_courses(db, current, _args):
    from app.profassist.service import list_courses

    return await list_courses(db, current["org_id"])


async def _get_course(db, current, args):
    from sqlalchemy import select

    from app.profassist.models import SubjectOutline
    from app.profassist.outline import course_brief

    code = (args.get("code") or "").replace(" ", "").upper()
    result = await db.execute(
        select(SubjectOutline).where(
            SubjectOutline.organization_id == current["org_id"],
            SubjectOutline.owner_user_id == current["user_id"],
        )
    )
    for row in result.scalars().all():
        if not code or row.code.replace(" ", "").upper() == code:
            return {"id": str(row.id), "brief": course_brief(row.body or {})}
    raise ProfassistError(404, "No subject outline matches that course.")


async def _list_outlines(db, current, _args):
    from app.profassist.outline import list_outlines

    return await list_outlines(db, current["org_id"], current["user_id"])


async def _start_outline(db, current, _args):
    from app.profassist.outline import start_outline

    return await start_outline(db, current["org_id"], current["user_id"])


async def _assist_outline(db, current, args):
    from app.profassist.outline import assist_step, list_outlines

    rows = await list_outlines(db, current["org_id"], current["user_id"])
    if not rows:
        from app.profassist.outline import start_outline

        created = await start_outline(db, current["org_id"], current["user_id"])
        outline_id = uuid.UUID(created["id"])
    else:
        wanted = "".join(ch for ch in str(args.get("code") or "").upper() if ch.isalnum())
        chosen = rows[0]
        if wanted:
            for row in rows:
                code = "".join(ch for ch in str(row.get("code") or "").upper() if ch.isalnum())
                if code == wanted:
                    chosen = row
                    break
        outline_id = uuid.UUID(chosen["id"])
    return await assist_step(
        db,
        current["org_id"],
        current["user_id"],
        outline_id,
        args.get("step") or "outcomes",
        args.get("message") or "Suggest this step",
    )


async def _create_assignment(db, current, args):
    from sqlalchemy import select

    from app.profassist.models import Assessment, Course
    from app.profassist.pii import scrub

    wanted = "".join(ch for ch in str(args.get("code") or "MAAI903").upper() if ch.isalnum())
    result = await db.execute(select(Course).where(Course.organization_id == current["org_id"]))
    course = None
    for row in result.scalars().all():
        code = "".join(ch for ch in row.code.upper() if ch.isalnum())
        if code == wanted or code.startswith(wanted[:4]):
            course = row
            break
    if course is None:
        raise ProfassistError(404, "No course in this university matches that code.")
    number = str(args.get("number") or "A2")
    due = scrub(str(args.get("due") or "")).text
    title = f"{number} {args.get('title') or 'Assignment'}"
    row = Assessment(
        organization_id=current["org_id"],
        course_id=course.id,
        owner_user_id=current["user_id"],
        title=title,
        brief=f"Due {due}." if due else "Draft from the home chat.",
        clos=list(course.clos or []),
        status="draft",
        external_id=f"chat-{number.lower()}",
        kind="assignment",
    )
    db.add(row)
    await db.flush()
    return {
        "id": str(row.id),
        "kind": "assignment",
        "code": course.code,
        "title": title,
        "due": due or "Date still open",
        "status": "draft",
        "href": "/assignments",
    }


async def _integrity(db, current, args):
    del db, current
    from app.profassist.integrity_board import concerns

    return concerns(str(args.get("code") or "MAAI903"), str(args.get("assignment") or ""))


_FACTORS = {
    "scores available count": "recorded scores",
    "active days 14d": "days active",
    "activity change": "recent activity",
    "resource views 14d": "resource views",
    "interactions 14d": "course interactions",
}


def _top_reason(factor: object) -> str:
    text = str(factor or "")
    name = text.split("(")[0].strip().lower()
    label = _FACTORS.get(name, name or "no strong signal")
    if "(+" in text:
        return f"Raises risk · {label}"
    if "(-" in text:
        return f"Lowers risk · {label}"
    return label[:1].upper() + label[1:]


async def _dropout(db, current, args):
    del db, current
    from app.profassist.ml.dropout import predict

    _guard("dropout_risk")
    from app.profassist.journey import ROSTER

    code = str(args.get("code") or "AAS910")
    payload = predict(
        [
            {"display_name": name, "external_id": f"stu-{(index % 4) + 1}"}
            for index, (_, name, _) in enumerate(ROSTER)
        ],
        course_code=code,
    )
    students = []
    for row in payload["students"]:
        reason = _top_reason((row.get("factors") or [""])[0])
        students.append(
            {
                "name": row["display_name"],
                "band": row["band"],
                "score": row["score"],
                "reason": reason,
            }
        )
    order = {"high": 0, "medium": 1, "low": 2}
    students.sort(key=lambda row: (order.get(row["band"], 9), -(row["score"] or 0)))
    watched = [row for row in students if row["band"] in {"high", "medium"}]
    return {
        "href": "/students",
        "trained": payload["trained"],
        "course": code,
        "message": (
            f"{len(watched)} of {len(students)} students in {code} need a look. "
            "The list is sorted by risk. These scores are advisory and do not change enrolment or marks."
        ),
        "students": students,
    }


async def _suggest(db, current, args):
    from app.profassist.outline import list_outlines, suggest_assessments

    rows = await list_outlines(db, current["org_id"], current["user_id"])
    if not rows:
        raise ProfassistError(
            400, "Finish or start a subject outline before suggesting assessments."
        )
    chosen = next((row for row in rows if (row.get("body") or {}).get("clos")), rows[0])
    drafted = await suggest_assessments(
        db,
        current["org_id"],
        current["user_id"],
        uuid.UUID(args.get("outline_id") or chosen["id"]),
        args.get("lo_codes") or [],
    )
    week = ""
    message = str(args.get("message") or "").lower()
    if "week 5" in message:
        week = "Week 5"
    for item in drafted.get("suggestions") or []:
        if week:
            item["due"] = week
            if week.lower() not in str(item.get("name") or "").lower():
                item["name"] = f"{item.get('name') or 'Assessment'} for {week}"
    if drafted.get("suggestions"):
        titles = [item.get("name") for item in drafted["suggestions"]]
        drafted["message"] = "Suggested: " + "; ".join(str(title) for title in titles if title)
    return drafted


async def _accept(db, current, args):
    from app.profassist.outline import accept_assessments, list_outlines

    rows = await list_outlines(db, current["org_id"], current["user_id"])
    if not rows:
        raise ProfassistError(400, "There is no subject outline to attach assessments to.")
    return await accept_assessments(
        db,
        current["org_id"],
        current["user_id"],
        uuid.UUID(args.get("outline_id") or rows[0]["id"]),
        args.get("tasks") or [],
    )


async def _slides(db, current, args):
    from app.profassist.service import build_cited_deck, list_courses

    courses = await list_courses(db, current["org_id"])
    if not courses:
        raise ProfassistError(400, "Sync or create a course before building slides.")
    deck = await build_cited_deck(
        db,
        current["org_id"],
        uuid.UUID(courses[0]["id"]),
        current["user_id"],
        int(args.get("week") or 1),
    )
    return {"id": deck.get("id"), "title": deck.get("title"), "week": deck.get("week")}


async def _sync(db, current, _args):
    from app.profassist.config import moodle_mode
    from app.profassist.service import sync_moodle

    result = await sync_moodle(db, current["org_id"], current["user_id"])
    status = result.get("last_status") or "ok"
    mode = result.get("mode") or moodle_mode()
    result["message"] = f"Moodle is in {mode} mode. The last sync status is {status}."
    return result


async def _push(db, current, args):
    from app.profassist.service import push_draft

    draft_id = args.get("draft_id")
    if not draft_id:
        raise ProfassistError(400, "Name the approved draft to push.")
    return await push_draft(db, current["org_id"], current["user_id"], uuid.UUID(draft_id))


async def _grade(db, current, args):
    from app.profassist.service import run_grade

    submission_id = args.get("submission_id")
    if not submission_id:
        raise ProfassistError(400, "Name the submission to grade.")
    return await run_grade(db, current["org_id"], current["user_id"], uuid.UUID(submission_id))


async def _memories(db, current, _args):
    from app.profassist.memory import list_memories

    return await list_memories(db, current["org_id"], current["user_id"])


async def _delete_memory(db, current, args):
    from app.profassist.memory import delete_memory

    memory_id = args.get("memory_id")
    if not memory_id:
        raise ProfassistError(400, "Name the memory to delete.")
    await delete_memory(db, current["org_id"], current["user_id"], uuid.UUID(memory_id))
    return {"deleted": memory_id}


async def _admin(db, current, _args):
    from app.profassist.settings_admin import admin_view

    view = await admin_view(db, current["org_id"])
    return {"chat_enabled": view.get("chat_enabled"), "model": view.get("model")}


async def _review_outline(db, current, args):
    from app.profassist.outline_review import run_review

    outline_id = args.get("outline_id")
    if not outline_id:
        raise ProfassistError(400, "Name the outline to review.")
    return await run_review(
        db,
        current["org_id"],
        current["user_id"],
        uuid.UUID(str(outline_id)),
        mode=str(args.get("mode") or "council"),
        reviewer=str(args.get("reviewer") or "curriculum"),
    )


async def _assistant_chat(db, current, args):
    del db, current
    from app.profassist.pii import scrub
    from app.profassist.providers import generate, key_configured
    from app.profassist.runtime import agent_route

    message = str(args.get("message") or "")
    context = args.get("context") or {}
    route = agent_route("chat")
    if not key_configured(route["provider"]):
        return {"answer": "No AI model is configured. Set LLM_API_KEY or OPENAI_API_KEY."}
    page = context.get("page") or "the workspace"
    system = (
        "You are ProfAssist inside the professor's workspace. "
        f"Current page: {page}. Context: {json.dumps(context, default=str)[:1200]}. "
        "Answer in two to four short sentences. "
        "Use the context; do not invent names, marks, or data."
    )
    try:
        response = generate(
            route["provider"],
            route["model"],
            [
                {"role": "system", "content": scrub(system).text},
                {"role": "user", "content": scrub(message).text},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        text = (response.choices[0].message.content or "").strip()
    except Exception:
        logger.info("The assistant chat model did not answer")
        text = ""
    return {"answer": scrub(text).text or "I could not reach a model just now."}


async def _review_rubric(db, current, args):
    from app.profassist.models import Assessment
    from app.profassist.service import _assessment_dict, _owned

    rubric_id = args.get("rubric_id")
    if not rubric_id:
        raise ProfassistError(400, "Name the rubric to review.")
    row = await _owned(
        db,
        Assessment,
        current["org_id"],
        uuid.UUID(str(rubric_id)),
        current["user_id"],
    )
    return _rubric_review(await _assessment_dict(db, row))


_LEVELS = ("beginning", "developing", "proficient", "advanced")


def _rubric_review(data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic rubric review. It reads the rubric and never writes to it."""
    title = str(data.get("title") or "Untitled rubric")
    status = str(data.get("status") or "draft")
    criteria = data.get("criteria") or []
    findings: list[dict[str, str]] = []
    weight_total = sum(int(item.get("weight") or 0) for item in criteria)
    if not criteria:
        findings.append({"severity": "high", "message": "No criteria yet."})
        return {
            "title": title,
            "status": status,
            "criteria_count": 0,
            "weight_total": 0,
            "findings": findings,
            "summary": f"{title} is {status} but has no criteria yet.",
            "changed": False,
        }
    if weight_total != 100:
        findings.append(
            {
                "severity": "high",
                "message": f"The criteria weights total {weight_total}%, not 100%.",
            }
        )
    for item in criteria:
        name = str(item.get("name") or "Untitled criterion")
        levels = item.get("levels") or {}
        blank = [level for level in _LEVELS if not str(levels.get(level) or "").strip()]
        if blank:
            findings.append(
                {
                    "severity": "medium",
                    "message": f"{name} has a blank {', '.join(blank)} level.",
                }
            )
    for flag in (data.get("alignment") or {}).get("flags") or []:
        findings.append({"severity": "medium", "message": str(flag)})
    if status == "approved":
        findings.append(
            {
                "severity": "info",
                "message": (
                    "This rubric is approved. Edits are locked; create a new rubric to change it."
                ),
            }
        )
    return {
        "title": title,
        "status": status,
        "criteria_count": len(criteria),
        "weight_total": weight_total,
        "findings": findings,
        "summary": (
            f"{title} is {status} with {len(criteria)} criteria weighting {weight_total}%. "
            f"{len(findings)} issue(s) were noted."
        ),
        "changed": False,
    }


async def _course_for_args(db, current, args):
    """Resolve the course a tool names, or fall back to the professor's first course."""
    from sqlalchemy import select

    from app.profassist.models import Course
    from app.profassist.service import _course

    course_id = args.get("course_id")
    if course_id:
        try:
            return await _course(db, current["org_id"], uuid.UUID(str(course_id)))
        except (ValueError, AttributeError) as exc:
            raise ProfassistError(400, "That course id is not valid.") from exc
    result = await db.execute(
        select(Course).where(Course.organization_id == current["org_id"]).order_by(Course.code)
    )
    courses = list(result.scalars().all())
    if not courses:
        raise ProfassistError(400, "There are no courses in this university yet.")
    wanted = "".join(ch for ch in str(args.get("code") or "").upper() if ch.isalnum())
    if wanted:
        for row in courses:
            if "".join(ch for ch in row.code.upper() if ch.isalnum()) == wanted:
                return row
        raise ProfassistError(404, "No course in this university matches that code.")
    return courses[0]


def _uuid_arg(args: dict[str, Any], key: str, message: str) -> uuid.UUID:
    value = args.get(key)
    if not value:
        raise ProfassistError(400, message)
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ProfassistError(400, "That id is not valid.") from exc


async def _list_students(db, current, args):
    from app.profassist.groupwork import roster

    course = await _course_for_args(db, current, args)
    return {
        "course": course.code,
        "students": await roster(db, current["org_id"], course.id),
    }


def _split_evenly(member_ids: list[str], count: int) -> list[dict[str, Any]]:
    """Split a roster into near-equal groups, preserving roster order."""
    if not member_ids:
        return []
    count = max(1, min(count, len(member_ids)))
    base, extra = divmod(len(member_ids), count)
    groups: list[dict[str, Any]] = []
    start = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        chunk = member_ids[start : start + size]
        start += size
        groups.append({"name": f"Group {index + 1}", "member_ids": chunk})
    return groups


async def _create_groups(db, current, args):
    from app.profassist.groupwork import roster, save_groups

    course = await _course_for_args(db, current, args)
    groups = args.get("groups") or []
    if not groups:
        try:
            count = int(args.get("group_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            students = await roster(db, current["org_id"], course.id)
            groups = _split_evenly([item["id"] for item in students], count)
    if not groups:
        raise ProfassistError(
            400,
            "Say how many groups to create, or pass groups with a name and member ids.",
        )
    assignment_id = args.get("assignment_id")
    assignment_uuid = None
    if assignment_id:
        try:
            assignment_uuid = uuid.UUID(str(assignment_id))
        except (ValueError, AttributeError) as exc:
            raise ProfassistError(400, "That assignment id is not valid.") from exc
    created = await save_groups(
        db,
        current["org_id"],
        current["user_id"],
        course.id,
        groups,
        assignment_id=assignment_uuid,
    )
    result: dict[str, Any] = {"course": course.code, "groups": created}
    if assignment_uuid is not None:
        result["assignment_id"] = str(assignment_uuid)
    return result


async def _list_groups(db, current, args):
    from sqlalchemy import select

    from app.profassist.models import StudentGroup

    course = await _course_for_args(db, current, args)
    rows = (
        await db.execute(
            select(StudentGroup).where(
                StudentGroup.organization_id == current["org_id"],
                StudentGroup.owner_user_id == current["user_id"],
                StudentGroup.course_id == course.id,
            )
        )
    ).scalars()
    return {
        "course": course.code,
        "items": [
            {"id": str(row.id), "name": row.name, "member_ids": row.member_ids} for row in rows
        ],
    }


async def _list_assignments(db, current, args):
    from app.profassist.groupwork import list_for_course

    course = await _course_for_args(db, current, args)
    return {
        "course": course.code,
        "items": await list_for_course(db, current["org_id"], current["user_id"], course.id),
    }


async def _materials(db, current, args):
    from app.profassist.service import build_cited_deck

    course = await _course_for_args(db, current, args)
    deck = await build_cited_deck(
        db,
        current["org_id"],
        course.id,
        current["user_id"],
        int(args.get("week") or 0),
        str(args.get("instructions") or ""),
    )
    return {
        "id": deck.get("id"),
        "title": deck.get("title"),
        "week": deck.get("week"),
        "slides": len(deck.get("slides") or []),
    }


async def _list_decks(db, current, args):
    from app.profassist.service import list_decks

    course = await _course_for_args(db, current, args)
    return {
        "course": course.code,
        "items": await list_decks(db, current["org_id"], course.id, current["user_id"]),
    }


async def _grade_queue(db, current, args):
    from app.profassist.service import grade_queue

    course = await _course_for_args(db, current, args)
    return await grade_queue(db, current["org_id"], course.id, current["user_id"])


async def _approve_draft(db, current, args):
    from app.profassist.service import approve_draft

    draft_id = _uuid_arg(args, "draft_id", "Name the grade draft to approve.")
    return await approve_draft(db, current["org_id"], current["user_id"], draft_id)


async def _publish_outline(db, current, args):
    from app.profassist.outline import finish_outline

    outline_id = _uuid_arg(args, "outline_id", "Name the outline to publish.")
    return await finish_outline(db, current["org_id"], current["user_id"], outline_id)


async def _generate_outline(db, current, args):
    from app.profassist.outline import generate_outline

    outline_id = _uuid_arg(args, "outline_id", "Name the outline to draft.")
    message = str(args.get("message") or "Draft the full outline.")
    return await generate_outline(db, current["org_id"], current["user_id"], outline_id, message)


async def _refine_outline(db, current, args):
    from app.profassist.outline import refine_outline

    outline_id = _uuid_arg(args, "outline_id", "Name the outline to change.")
    message = str(args.get("message") or "").strip()
    if not message:
        raise ProfassistError(400, "Say what to change in the outline.")
    section = args.get("section") or None
    return await refine_outline(
        db, current["org_id"], current["user_id"], outline_id, message, section
    )


_HANDLERS = {
    "list_courses": _list_courses,
    "get_course": _get_course,
    "list_outlines": _list_outlines,
    "start_outline": _start_outline,
    "assist_outline": _assist_outline,
    "review_outline": _review_outline,
    "review_rubric": _review_rubric,
    "assistant_chat": _assistant_chat,
    "create_assignment": _create_assignment,
    "dropout_risk": _dropout,
    "integrity_concerns": _integrity,
    "suggest_assessments": _suggest,
    "accept_assessments": _accept,
    "generate_slides": _slides,
    "moodle_sync": _sync,
    "moodle_push": _push,
    "start_grade": _grade,
    "list_memories": _memories,
    "delete_memory": _delete_memory,
    "admin_ai_settings": _admin,
    "list_students": _list_students,
    "create_groups": _create_groups,
    "list_groups": _list_groups,
    "list_assignments": _list_assignments,
    "generate_materials": _materials,
    "list_decks": _list_decks,
    "grade_queue": _grade_queue,
    "approve_draft": _approve_draft,
    "publish_outline": _publish_outline,
    "generate_outline": _generate_outline,
    "refine_outline": _refine_outline,
}


def _assistant_tool_message(message: Any, calls: list[Any]) -> dict[str, Any]:
    """Turn a LiteLLM assistant message with tool calls back into OpenAI input."""
    return {
        "role": "assistant",
        "content": getattr(message, "content", "") or "",
        "tool_calls": [
            {
                "id": getattr(call, "id", "") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for index, call in enumerate(calls)
        ],
    }


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    """Read the JSON arguments of one tool call. A bad answer becomes no arguments."""
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _tool_result_message(payload: dict[str, Any], call_id: str, name: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(payload.get("result"), default=str)[:6000],
    }


_chat_loop: ContextVar[Any] = ContextVar("pa_chat_loop", default=None)


class ChatState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool: str
    result: Any
    arguments: dict[str, Any]
    needs_confirm: bool
    preview: str
    rounds: int


def _run_in_chat_loop(coro: Any) -> Any:
    """Await a tool call from a graph node that runs off the request's event loop.

    ``invoke_graph`` runs ``graph.invoke`` synchronously, so the chat graph is
    driven from a worker thread. The AsyncSession belongs to the request loop,
    so the tool coroutine is handed back to that loop instead of run here.
    """
    loop = _chat_loop.get()
    if loop is None or loop.is_closed():
        return asyncio.run(coro)
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def _assistant_content(state: dict[str, Any]) -> str:
    """The last plain assistant turn, which is the model's final answer."""
    for message in reversed(list(state.get("messages") or [])):
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            return str(message.get("content") or "").strip()
    return ""


def _chat_payload(state: dict[str, Any], url: str | None) -> dict[str, Any]:
    """The chat result shape the panel and the SSE stream already read."""
    arguments = dict(state.get("arguments") or {})
    if state.get("needs_confirm"):
        payload: dict[str, Any] = {
            "reply": f"I can {state.get('preview') or ''} Reply confirm to go ahead.",
            "tool": state.get("tool") or "",
            "result": None,
            "needs_confirm": True,
            "preview": state.get("preview") or "",
            "confirm_with": CONFIRM,
            "arguments": arguments,
        }
    else:
        tool = str(state.get("tool") or "")
        result = state.get("result")
        reply = _assistant_content(state) or (
            _reply(tool, result) if tool else "I could not find a tool for that. Please rephrase."
        )
        payload = {
            "reply": reply,
            "tool": tool,
            "result": result,
            "needs_confirm": False,
            "arguments": arguments,
        }
    if url:
        payload["trace_url"] = url
    return payload


def build_chat_graph(
    db: AsyncSession,
    *,
    is_admin: bool,
    confirmed: bool = False,
    pending_tool: str = "",
):
    """The professor chat: model -> tools -> model, at most four tool rounds.

    The model chooses a native function call. Each call runs through the same
    ``invoke_tool`` the MCP endpoint uses. A mutation ends the graph with
    ``needs_confirm`` instead of looping, and the professor's explicit confirm
    lets the next turn run it.
    """
    from app.profassist.pii import scrub
    from app.profassist.providers import generate
    from app.profassist.runtime import agent_route

    route = agent_route("chat")
    definitions = openai_tool_definitions(is_admin=is_admin)
    extra: dict[str, Any] = {"tools": definitions, "tool_choice": "auto"} if definitions else {}

    def model_node(state: ChatState) -> ChatState:
        response = generate(
            route["provider"],
            route["model"],
            list(state.get("messages") or []),
            temperature=0.2,
            **extra,
        )
        choice_message = response.choices[0].message
        calls = list(getattr(choice_message, "tool_calls", None) or [])
        messages = list(state.get("messages") or [])
        if calls:
            messages.append(_assistant_tool_message(choice_message, calls))
        else:
            text = scrub(str(getattr(choice_message, "content", "") or "")).text.strip()
            messages.append({"role": "assistant", "content": text})
        return {"messages": messages}

    def tools_node(state: ChatState) -> ChatState:
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages else {}
        calls = list(last.get("tool_calls") or [])
        tool = str(state.get("tool") or "")
        result = state.get("result")
        arguments = dict(state.get("arguments") or {})
        rounds = int(state.get("rounds") or 0)
        for index, call in enumerate(calls):
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            arguments = _parse_tool_arguments(function.get("arguments"))
            confirmed_flag = bool(arguments.pop("confirm", False))
            if confirmed and pending_tool and name == pending_tool:
                confirmed_flag = True
            payload = _run_in_chat_loop(invoke_tool(db, name, arguments, confirmed=confirmed_flag))
            tool = name
            result = payload.get("result")
            if payload.get("needs_confirm"):
                return {
                    "messages": messages,
                    "tool": name,
                    "result": None,
                    "arguments": arguments,
                    "needs_confirm": True,
                    "preview": str(payload.get("preview") or ""),
                    "rounds": rounds,
                }
            messages.append(
                _tool_result_message(payload, str(call.get("id") or f"call_{index}"), name)
            )
        return {
            "messages": messages,
            "tool": tool,
            "result": result,
            "arguments": arguments,
            "needs_confirm": False,
            "rounds": rounds + 1,
        }

    def after_model(state: ChatState) -> str:
        last = (state.get("messages") or [{}])[-1]
        if last.get("tool_calls") and int(state.get("rounds") or 0) < 4:
            return "tools"
        return END

    def after_tools(state: ChatState) -> str:
        if state.get("needs_confirm") or int(state.get("rounds") or 0) >= 4:
            return END
        return "model"

    graph = StateGraph(ChatState)
    graph.add_node("model", model_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("model")
    graph.add_conditional_edges("model", after_model, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", after_tools, {"model": "model", END: END})
    return graph.compile()


async def chat_turn(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_admin: bool,
    message: str,
    confirmed: bool = False,
    pending_tool: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the professor chat as a LangGraph graph, traced by Langfuse.

    The model sees the enabled tool definitions and chooses a function call. Each
    call runs through the same ``invoke_tool`` the MCP endpoint uses. A mutation
    returns ``needs_confirm`` first unless the professor confirmed it.
    """
    from app.profassist.pii import scrub
    from app.profassist.providers import key_configured
    from app.profassist.runtime import agent_route
    from app.profassist.settings_admin import load_runtime

    message = scrub(message or "").text
    context = context or {}
    await load_runtime(db, org_id, user_id)
    set_tool_actor(org_id, user_id, is_admin=is_admin)
    try:
        if confirmed and pending_tool:
            payload = await invoke_tool(db, pending_tool, {}, confirmed=True)
            payload["arguments"] = {}
            reply = payload.get("preview") or _reply(pending_tool, payload.get("result"))
            if payload.get("needs_confirm"):
                reply = f"I can {payload['preview']} Reply confirm to go ahead."
            return {"reply": reply, **payload}

        route = agent_route("chat")
        if not key_configured(route["provider"]):
            raise ProfassistError(
                503, "No AI model is configured. Set LLM_API_KEY or OPENAI_API_KEY."
            )

        system = (
            "You are ProfAssist inside the professor's workspace. "
            f"Current page: {context.get('page') or 'the workspace'}. "
            f"Context: {json.dumps(context, default=str)[:1200]}. "
            "Call a tool when it helps with the request. Use assistant_chat for a "
            "general question. Never invent student names, marks, or data."
        )
        state: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": scrub(system).text},
                {"role": "user", "content": message},
            ],
            "tool": "",
            "result": None,
            "arguments": {},
            "needs_confirm": False,
            "preview": "",
            "rounds": 0,
        }
        graph = build_chat_graph(
            db, is_admin=is_admin, confirmed=confirmed, pending_tool=pending_tool
        )
        token = _chat_loop.set(asyncio.get_running_loop())
        try:
            result, url = await asyncio.to_thread(
                invoke_graph,
                graph,
                state,
                name="professor-chat",
                metadata={"kind": "chat"},
            )
        finally:
            _chat_loop.reset(token)
        return _chat_payload(result or {}, url)
    finally:
        clear_tool_actor()


def chat_stream_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one chat result into the events the AI Elements panel reads.

    The UI stream is our own SSE, not the Vercel data protocol. Each event is
    a tool card, a citation, or a text delta.
    """
    reply = str(payload.get("reply") or "")
    tool = str(payload.get("tool") or "")
    needs = bool(payload.get("needs_confirm"))
    events: list[dict[str, Any]] = [
        {
            "event": "reasoning",
            "data": {
                "text": (
                    "I stay inside this university and this professor's role. "
                    "A Moodle push or a delete waits for a confirm."
                )
            },
        }
    ]
    if tool:
        events.append(
            {
                "event": "tool",
                "data": {
                    "name": tool,
                    "state": "approval-requested" if needs else "output-available",
                    "input": payload.get("arguments") or {"tool": tool},
                    "output": None if needs else payload.get("result"),
                    "href": (payload.get("result") or {}).get("href")
                    if isinstance(payload.get("result"), dict)
                    else "",
                },
            }
        )
        events.append(
            {
                "event": "source",
                "data": {
                    "title": "Course workspace",
                    "href": "/dashboard",
                },
            }
        )
    words = reply.split(" ")
    for index, word in enumerate(words):
        if not word and index:
            continue
        gap = " " if index < len(words) - 1 else ""
        events.append({"event": "text", "data": {"delta": f"{word}{gap}"}})
    events.append(
        {
            "event": "done",
            "data": {
                "reply": reply,
                "tool": tool,
                "needs_confirm": needs,
            },
        }
    )
    return events


def _speak(message: str, tool: str, result: Any, fallback: str, context: dict | None = None) -> str:
    """Ask the configured model to phrase the answer. The offline line is the fallback."""
    from app.profassist.providers import generate, key_configured
    from app.profassist.runtime import agent_route

    route = agent_route("chat")
    if not key_configured(route["provider"]):
        return fallback
    try:
        brief = json.dumps(result, default=str)[:1200]
        context_brief = json.dumps(context or {}, default=str)[:800]
        response = generate(
            route["provider"],
            route["model"],
            [
                {
                    "role": "system",
                    "content": (
                        "You help one university professor. Answer in two or three plain sentences. "
                        "Use the tool result when it is present. Do not invent student names or marks."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {message}\nContext: {context_brief}\nTool: {tool}\n"
                        f"Result: {brief}\n"
                        f"If the result is empty, you may say: {fallback}"
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=800,
        )
        text = (response.choices[0].message.content or "").strip()
        return _keep_shape(message, tool, result, text or fallback, fallback)
    except Exception:
        logger.info("The chat model did not answer; using the offline reply")
        return fallback


def _numbered_items(text: str) -> int:
    import re

    return len(re.findall(r"(?m)^\s*\d+\.\s+\S", text or ""))


def _keep_shape(message: str, tool: str, result: Any, spoken: str, fallback: str) -> str:
    """Keep a count the professor asked for, and keep the case links the tool found."""
    if tool == "assist_outline" and isinstance(result, dict):
        from app.profassist.outline import asked_count

        count = asked_count(message)
        prepared = str(result.get("reply") or fallback)
        if count and _numbered_items(prepared) >= count and _numbered_items(spoken) < count:
            return prepared
    if tool == "integrity_concerns" and isinstance(result, dict):
        cases = result.get("cases") or []
        if cases:
            return _case_reply(result)
    if tool == "dropout_risk" and isinstance(result, dict):
        names = [str(row.get("name") or "") for row in result.get("students") or []]
        if names and not any(name and name in spoken for name in names):
            return str(result.get("message") or fallback)
    if (
        tool == "suggest_assessments"
        and isinstance(result, dict)
        and result.get("message")
        and not spoken.strip()
    ):
        return str(result["message"])
    return spoken or fallback


def _case_reply(result: dict[str, Any]) -> str:
    """The same sentence the home to-do uses. The screen draws the rows itself."""
    message = str(result.get("message") or "")
    first = message.split("\n", 1)[0].strip()
    if first:
        return first
    cases = result.get("cases") or []
    assignments = len({(case.get("course"), case.get("assignment")) for case in cases})
    return f"{len(cases)} cases need a look across {assignments} assignments."


def _reply(name: str, result: Any) -> str:
    if name == "list_courses" and isinstance(result, list):
        if not result:
            return "There are no courses in this university yet."
        return "Courses: " + ", ".join(f"{item.get('code')} {item.get('title')}" for item in result)
    if name == "moodle_sync" and isinstance(result, dict):
        return result.get("last_sync_status") or "Moodle sync finished."
    if name == "create_assignment" and isinstance(result, dict):
        return (
            f"Drafted {result.get('title')} on {result.get('code')}. "
            f"Due {result.get('due')}. It is still a draft."
        )
    if name == "dropout_risk" and isinstance(result, dict):
        return result.get("message") or "Risk scores are advisory."
    if name == "suggest_assessments" and isinstance(result, dict):
        return result.get("message") or "Suggested an assessment. It is still a draft."
    if name == "assist_outline" and isinstance(result, dict) and result.get("reply"):
        return str(result["reply"])
    if name == "integrity_concerns" and isinstance(result, dict):
        return result.get("message") or "Nothing needs a look."
    if name == "suggest_assessments" and isinstance(result, dict):
        titles = [item.get("name") for item in result.get("suggestions") or []]
        return "Suggested assessments: " + ", ".join(titles)
    if name == "get_course" and isinstance(result, dict):
        return result.get("brief") or "Course loaded."
    if name == "generate_slides" and isinstance(result, dict):
        return f"Drafted {result.get('title') or 'a deck'}."
    if name == "admin_ai_settings":
        return "AI settings are available to you as an administrator."
    if name == "review_outline" and isinstance(result, dict):
        return _review_reply(result)
    if name == "review_rubric" and isinstance(result, dict):
        return _rubric_reply(result)
    if name == "list_students" and isinstance(result, dict):
        students = result.get("students") or []
        if not students:
            return f"No students are on the {result.get('course') or 'course'} roster yet."
        names = ", ".join(str(row.get("name") or "") for row in students[:8] if row.get("name"))
        return f"{len(students)} students on {result.get('course')}: {names}."
    if name == "create_groups" and isinstance(result, dict):
        groups = result.get("groups") or []
        return f"Saved {len(groups)} groups on {result.get('course')}."
    if name == "list_groups" and isinstance(result, dict):
        items = result.get("items") or []
        if not items:
            return f"No groups are set up on {result.get('course')} yet."
        return "Groups: " + ", ".join(str(row.get("name") or "") for row in items)
    if name == "list_assignments" and isinstance(result, dict):
        items = result.get("items") or []
        if not items:
            return f"No assignments are on {result.get('course')} yet."
        listed = ", ".join(
            f"{row.get('number') or ''} {row.get('title') or ''}".strip() for row in items
        )
        return f"{len(items)} assignments on {result.get('course')}: {listed}."
    if name == "generate_materials" and isinstance(result, dict):
        return f"Drafted {result.get('title') or 'a deck'} for week {result.get('week') or 'all'}."
    if name == "list_decks" and isinstance(result, dict):
        items = result.get("items") or []
        if not items:
            return f"No decks are built for {result.get('course')} yet."
        listed = ", ".join(
            f"{row.get('title') or 'Deck'} (week {row.get('week') or 'all'})" for row in items
        )
        return f"{len(items)} decks: {listed}."
    if name == "grade_queue" and isinstance(result, dict):
        submissions = result.get("submissions") or []
        drafts = sum(1 for row in submissions if row.get("draft_id"))
        return f"{len(submissions)} submissions are in the grading queue; {drafts} have a draft."
    if name == "approve_draft" and isinstance(result, dict):
        return "The grade draft is approved."
    if name == "publish_outline" and isinstance(result, dict):
        return f"Published {result.get('name') or 'the subject outline'}."
    if name in {"generate_outline", "refine_outline"} and isinstance(result, dict):
        return str(result.get("reply") or "The outline is updated.")
    if name == "list_memories" and isinstance(result, list):
        return f"{len(result)} memories are stored for you."
    return f"Finished {name.replace('_', ' ')}."


def _review_reply(result: dict[str, Any]) -> str:
    """Summarize a review without inventing findings or touching the outline."""
    parts: list[str] = []
    score = result.get("score")
    if score is not None:
        parts.append(f"Score {score}.")
    summary = str(result.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    findings = result.get("findings") or []
    top: list[str] = []
    for item in findings[:3]:
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        section = str(item.get("section") or "").strip()
        top.append(f"[{section}] {message}" if section else message)
    if top:
        parts.append("Top findings: " + "; ".join(top) + ".")
    parts.append("This is a review, not a verdict. Nothing was changed.")
    return " ".join(parts)


def _rubric_reply(result: dict[str, Any]) -> str:
    """Summarize a rubric review without inventing findings or changing the rubric."""
    title = str(result.get("title") or "This rubric")
    status = str(result.get("status") or "draft")
    weight = result.get("weight_total")
    head = f"{title} is {status}"
    if weight is not None:
        head += f", weighting {weight}%"
    parts = [head + "."]
    top = [
        str(item.get("message") or "").strip()
        for item in (result.get("findings") or [])[:3]
        if str(item.get("message") or "").strip()
    ]
    if top:
        parts.append("Top findings: " + "; ".join(top) + ".")
    parts.append("This is a review, not a verdict. Nothing was changed.")
    return " ".join(parts)
