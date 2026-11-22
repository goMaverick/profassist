"""Professor tools shared by the chat and the MCP server.

Every tool checks the signed-in professor and her university. Moodle push and
deletes wait for an explicit confirm token.
"""

import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.runtime import tool_enabled

_actor: ContextVar[dict[str, Any] | None] = ContextVar("pa_tool_actor", default=None)

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
        "summary": "Sync the fake or real Moodle catalogue.",
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


def choose_tool(message: str) -> tuple[str, dict[str, Any]]:
    """Demo router. A model key is not required."""
    text = (message or "").lower()
    if "sync" in text and "moodle" in text:
        return "moodle_sync", {}
    if "push" in text and "grade" in text:
        return "moodle_push", {}
    if "slide" in text:
        week = 1
        for token in text.split():
            if token.isdigit():
                week = int(token)
        return "generate_slides", {"week": week}
    if "assignment" in text and any(word in text for word in ("create", "add", "draft")):
        return "create_assignment", _assignment_args(text)
    if "dropout" in text or "at risk" in text or "at-risk" in text:
        return "dropout_risk", {}
    if "similar" in text:
        return "list_courses", {}
    if "group" in text:
        return "list_courses", {}
    if "assessment" in text and ("suggest" in text or "generat" in text):
        return "suggest_assessments", {}
    if "wizard" in text or "outline" in text:
        return "assist_outline", {"step": "outcomes"}
    if "memor" in text:
        return "list_memories", {}
    if "setting" in text or "admin" in text:
        return "admin_ai_settings", {}
    if "grade" in text:
        return "list_courses", {}
    return "list_courses", {}


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

        created = await start_outline(db, current["org_id"], current["user_id"], demo=False)
        outline_id = uuid.UUID(created["id"])
    else:
        outline_id = uuid.UUID(rows[0]["id"])
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
        "href": "/generate",
    }


async def _dropout(db, current, _args):
    del db
    from app.profassist.ml.dropout import predict

    _guard("dropout_risk")
    payload = predict(
        [
            {"display_name": "Sara Al Maktoum", "external_id": "stu-1"},
            {"display_name": "Omar Haddad", "external_id": "stu-2"},
        ],
        course_code="MAAI903",
    )
    return {
        "href": "/students",
        "trained": payload["trained"],
        "message": payload["message"],
        "students": [
            {
                "name": row["display_name"],
                "band": row["band"],
                "score": row["score"],
            }
            for row in payload["students"]
        ],
    }


async def _suggest(db, current, args):
    from app.profassist.outline import list_outlines, suggest_assessments

    rows = await list_outlines(db, current["org_id"], current["user_id"])
    if not rows:
        raise ProfassistError(
            400, "Finish or start a subject outline before suggesting assessments."
        )
    return await suggest_assessments(
        db,
        current["org_id"],
        current["user_id"],
        uuid.UUID(args.get("outline_id") or rows[0]["id"]),
        args.get("lo_codes") or [],
    )


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
    from app.profassist.service import sync_moodle

    return await sync_moodle(db, current["org_id"], current["user_id"])


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


_HANDLERS = {
    "list_courses": _list_courses,
    "get_course": _get_course,
    "list_outlines": _list_outlines,
    "start_outline": _start_outline,
    "assist_outline": _assist_outline,
    "create_assignment": _create_assignment,
    "dropout_risk": _dropout,
    "suggest_assessments": _suggest,
    "accept_assessments": _accept,
    "generate_slides": _slides,
    "moodle_sync": _sync,
    "moodle_push": _push,
    "start_grade": _grade,
    "list_memories": _memories,
    "delete_memory": _delete_memory,
    "admin_ai_settings": _admin,
}


async def chat_turn(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_admin: bool,
    message: str,
    confirmed: bool = False,
    pending_tool: str = "",
) -> dict[str, Any]:
    from app.profassist.pii import scrub

    message = scrub(message or "").text
    set_tool_actor(org_id, user_id, is_admin=is_admin)
    try:
        if confirmed and pending_tool:
            name, arguments = pending_tool, {}
            confirmed_flag = True
        else:
            from typing import TypedDict

            from langgraph.graph import END, StateGraph

            from app.profassist.observe import invoke_graph

            class ChatState(TypedDict, total=False):
                message: str
                name: str
                arguments: dict

            def pick(state: ChatState) -> ChatState:
                picked, args = choose_tool(state.get("message") or "")
                return {"name": picked, "arguments": args}

            graph = StateGraph(ChatState)
            graph.add_node("pick", pick)
            graph.set_entry_point("pick")
            graph.add_edge("pick", END)
            chosen, _url = invoke_graph(
                graph.compile(),
                {"message": message},
                name="professor-chat",
                metadata={"kind": "chat"},
            )
            name = chosen.get("name") or "list_courses"
            arguments = chosen.get("arguments") or {}
            confirmed_flag = False
        payload = await invoke_tool(db, name, arguments, confirmed=confirmed_flag)
        payload["arguments"] = arguments
        if payload.get("needs_confirm"):
            reply = f"I can {payload['preview']} Reply confirm to go ahead."
        else:
            reply = _reply(name, payload.get("result"))
        return {"reply": reply, **payload}
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
                    "href": "https://demo.uowd.ac.ae/dashboard",
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
        titles = [item.get("name") for item in result.get("suggestions") or []]
        return "Suggested assessments: " + ", ".join(titles)
    if name == "get_course" and isinstance(result, dict):
        return result.get("brief") or "Course loaded."
    if name == "generate_slides" and isinstance(result, dict):
        return f"Drafted {result.get('title') or 'a deck'}."
    if name == "admin_ai_settings":
        return "AI settings are available to you as an administrator."
    if name == "list_memories" and isinstance(result, list):
        return f"{len(result)} memories are stored for you."
    return f"Finished {name.replace('_', ' ')}."
