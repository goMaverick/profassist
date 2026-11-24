"""Professor API. Drafts stay drafts until she approves them."""

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentAppAdmin, CurrentUser, DBSession
from app.integrations.moodle.gateway import launch as moodle_launch
from app.profassist.briefing import build_briefing
from app.profassist.council_script import script_for
from app.profassist.course_memory.service import (
    load_dossier,
    rebuild_course_memory,
    rebuild_material,
)
from app.profassist.deps import ProfOrg
from app.profassist.design import approve_design, draft_design, get_design, save_design
from app.profassist.groupwork import (
    allocate,
    assess_summary,
    assignment_view,
    create_from_task,
    draft_text,
    list_for_course,
    list_submissions,
    propose_ideas,
    publish_assignment,
    roster,
    save_groups,
    save_ideas,
    similarity_report,
    write_exemplars,
)
from app.profassist.memory import delete_memory, list_memories
from app.profassist.outline import (
    STEPS,
    accept_assessments,
    assist_step,
    attach_file,
    document_bytes,
    finish_outline,
    get_outline,
    list_outlines,
    outline_context,
    remove_outline_material,
    save_instructions,
    save_step,
    start_outline,
    suggest_assessments,
)
from app.profassist.outline_review import apply_review_fix, run_review
from app.profassist.platform_tools import chat_stream_events, chat_turn, tool_catalog
from app.profassist.service import (
    add_material,
    approve_assessment,
    approve_deck,
    approve_draft,
    approve_objective,
    approve_reflection,
    build_cited_deck,
    calibrator_page,
    capture_movement,
    check_rubric,
    create_rubric,
    deck_bytes,
    delete_material,
    draft_assessment,
    draft_objectives,
    draft_slides,
    edit_draft,
    get_assessment,
    get_draft,
    get_style,
    get_submission,
    grade_assignment_batch,
    grade_queue,
    home,
    import_rubric,
    list_assessments,
    list_courses,
    list_decks,
    list_flags,
    list_materials,
    list_objectives,
    list_reflections,
    list_students,
    push_draft,
    push_record,
    reset_about,
    reveal_draft,
    run_grade,
    run_reflection,
    save_about,
    save_rubric,
    save_style,
    save_template,
    scan_integrity,
    set_flag,
    upload_submission_zip,
)
from app.profassist.settings_admin import admin_view, save_model_settings, save_prompt, set_tool
from app.profassist.tracking import list_registered_models_async
from app.profassist.visuals import page_visuals

router = APIRouter()


class TextBody(BaseModel):
    soul_md: str = Field(min_length=1)


class AboutBody(BaseModel):
    about_md: str = ""


class EditBody(BaseModel):
    overall_feedback: str = ""
    levels: dict[str, str] = Field(default_factory=dict)


class FlagBody(BaseModel):
    status: str


class LaunchBody(BaseModel):
    claims: dict = Field(default_factory=dict)


class DesignChatBody(BaseModel):
    message: str = ""


class DesignSaveBody(BaseModel):
    reply: str = ""
    weeks: list = Field(default_factory=list)
    clos: list = Field(default_factory=list)
    plan: list = Field(default_factory=list)


class RubricCreateBody(BaseModel):
    title: str = "Untitled rubric"


class RubricSaveBody(BaseModel):
    brief: str = ""
    criteria: list = Field(default_factory=list)


class RubricPasteBody(BaseModel):
    pasted: str = ""


class BriefingBody(BaseModel):
    course_id: uuid.UUID | None = None


@router.get("/home")
async def home_view(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await home(db, org.id, user.id)


@router.post("/home/briefing")
async def home_briefing(
    user: CurrentUser, org: ProfOrg, db: DBSession, body: BriefingBody | None = None
) -> dict:
    return await build_briefing(db, org.id, user.id, body.course_id if body else None)


@router.get("/visuals")
async def visuals_view(user: CurrentUser, org: ProfOrg, page: str = "home") -> dict:
    del user, org
    return page_visuals(page)


@router.get("/courses")
async def courses(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_courses(db, org.id)}


@router.post("/lti/launch")
async def lti_launch(body: LaunchBody, user: CurrentUser, org: ProfOrg) -> dict:
    return await moodle_launch(body.claims)


@router.get("/courses/{course_id}/materials")
async def materials(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_materials(db, org.id, course_id, user.id)}


@router.post("/courses/{course_id}/materials")
async def upload_material(
    course_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    data = await file.read()
    material = await add_material(
        db, org.id, course_id, user.id, file.filename or "notes.txt", data
    )
    if material.get("status") == "ready" and not (material.get("pii_report") or {}).get(
        "quarantined"
    ):
        # Prefect runs after the response; a slow rebuild never blocks the upload.
        from app.worker.tasks.profassist_tasks import course_memory_flow

        background.add_task(course_memory_flow, str(org.id), str(course_id), str(user.id))
    return material


@router.delete("/courses/{course_id}/materials/{material_id}")
async def remove_material(
    course_id: uuid.UUID,
    material_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    return await delete_material(db, org.id, course_id, user.id, material_id)


@router.get("/courses/{course_id}/memory")
async def course_memory(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    # A foreign course must 404 before the dossier lookup.
    materials = await list_materials(db, org.id, course_id, user.id)
    dossier = await load_dossier(db, org.id, user.id, course_id)
    from app.profassist.models import Course
    from app.profassist.slide_memory import artifact_preferences, slide_preferences

    course = await db.get(Course, course_id)
    code = ""
    if course is not None and course.organization_id == org.id:
        code = str(course.code or "").strip()
    query = f"{code} slides" if code else "slides"
    preferences = await slide_preferences(db, org.id, user.id, query=query, limit=5)
    artifact_query = f"{code} outline assignment rubric" if code else "outline assignment rubric"
    artifacts = await artifact_preferences(db, org.id, user.id, query=artifact_query, limit=6)
    return {
        "dossier": dossier,
        "materials": materials,
        "slide_preferences": preferences,
        "artifact_preferences": artifacts,
    }


@router.post("/courses/{course_id}/memory/rebuild")
async def course_memory_rebuild(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    # Keep the ownership check: a rebuild must never create a foreign dossier.
    await list_materials(db, org.id, course_id, user.id)
    result = await rebuild_course_memory(db, org.id, user.id, course_id)
    return {
        "status": str((result.get("dossier") or {}).get("status") or ""),
        "trace_url": str(result.get("trace_url") or ""),
        "materials": result.get("materials") or [],
    }


@router.post("/materials/{material_id}/extract")
async def material_extract(
    material_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await rebuild_material(db, org.id, user.id, material_id)


@router.post("/courses/{course_id}/objectives/draft")
async def objectives_draft(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await draft_objectives(db, org.id, course_id, user.id)}


@router.get("/courses/{course_id}/objectives")
async def objectives(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_objectives(db, org.id, course_id, user.id)}


@router.post("/objectives/{objective_id}/approve")
async def objective_approve(
    objective_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_objective(db, org.id, user.id, objective_id)


@router.post("/courses/{course_id}/slides/draft")
async def slides_draft(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await draft_slides(db, org.id, course_id, user.id)


@router.get("/courses/{course_id}/slides")
async def slides(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_decks(db, org.id, course_id, user.id)}


@router.post("/slides/{deck_id}/approve")
async def slides_approve(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_deck(db, org.id, user.id, deck_id)


@router.get("/slides/{deck_id}/pptx")
async def slides_pptx(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> Response:
    filename, data = await deck_bytes(db, org.id, user.id, deck_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/courses/{course_id}/assessment/draft")
async def assessment_draft(
    course_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    assessment_id: uuid.UUID | None = Query(default=None),
) -> dict:
    return await draft_assessment(db, org.id, course_id, user.id, assessment_id)


@router.get("/courses/{course_id}/assessment")
async def assessment(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"assessment": await get_assessment(db, org.id, course_id, user.id)}


@router.get("/courses/{course_id}/design")
async def design_view(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await get_design(db, org.id, course_id, user.id)


@router.post("/courses/{course_id}/design/draft")
async def design_draft(
    course_id: uuid.UUID, body: DesignChatBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await draft_design(db, org.id, course_id, user.id, body.message)


@router.put("/courses/{course_id}/design")
async def design_save(
    course_id: uuid.UUID, body: DesignSaveBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await save_design(db, org.id, course_id, user.id, body.model_dump())


@router.post("/courses/{course_id}/design/approve")
async def design_approve(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_design(db, org.id, course_id, user.id)


@router.get("/courses/{course_id}/assessments")
async def assessments(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_assessments(db, org.id, course_id, user.id)}


@router.post("/courses/{course_id}/rubrics")
async def rubric_create(
    course_id: uuid.UUID, body: RubricCreateBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await create_rubric(db, org.id, course_id, user.id, body.title)


@router.put("/assessments/{assessment_id}/rubric")
async def rubric_save(
    assessment_id: uuid.UUID, body: RubricSaveBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await save_rubric(db, org.id, user.id, assessment_id, body.criteria, body.brief)


@router.post("/assessments/{assessment_id}/import")
async def rubric_import(
    assessment_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
) -> dict:
    data = await file.read() if file is not None else b""
    return await import_rubric(
        db, org.id, user.id, assessment_id, file.filename if file else "", data, pasted
    )


@router.post("/assessments/{assessment_id}/check")
async def rubric_check(
    assessment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await check_rubric(db, org.id, user.id, assessment_id)


@router.post("/courses/{course_id}/submissions/upload")
async def submission_upload(
    course_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    assessment_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
) -> dict:
    return await upload_submission_zip(
        db, org.id, course_id, user.id, assessment_id, await file.read()
    )


@router.post("/assessments/{assessment_id}/grade-batch")
async def grade_batch(
    assessment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await grade_assignment_batch(db, org.id, user.id, assessment_id)


@router.post("/assessments/{assessment_id}/approve")
async def assessment_approve(
    assessment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_assessment(db, org.id, user.id, assessment_id)


@router.post("/assessments/{assessment_id}/push")
async def assessment_push(
    assessment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.models import Assessment

    row = await db.get(Assessment, assessment_id)
    if row is None or row.organization_id != org.id:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(404, "Assessment not found in this workspace")
    owner = getattr(row, "owner_user_id", None)
    if owner is not None and owner != user.id:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(404, "Assessment not found in this workspace")
    receipt = await push_record(
        db,
        org.id,
        user.id,
        "assessment",
        str(row.id),
        row.status,
        {"title": row.title, "brief": row.brief},
    )
    return {"receipt": receipt}


@router.get("/courses/{course_id}/grade")
async def grade(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await grade_queue(db, org.id, course_id, user.id)


@router.get("/submissions/{submission_id}")
async def submission(
    submission_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await get_submission(db, org.id, submission_id)


@router.post("/submissions/{submission_id}/grade")
async def grade_one(
    submission_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await run_grade(db, org.id, user.id, submission_id)


@router.get("/drafts/{draft_id}")
async def draft(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await get_draft(db, org.id, user.id, draft_id)


@router.post("/drafts/{draft_id}/reveal")
async def draft_reveal(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await reveal_draft(db, org.id, user.id, draft_id)


@router.post("/drafts/{draft_id}/edit")
async def draft_edit(
    draft_id: uuid.UUID, body: EditBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await edit_draft(db, org.id, user.id, draft_id, body.overall_feedback, body.levels)


@router.post("/drafts/{draft_id}/approve")
async def draft_approve(
    draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.grade_notes import release_feedback
    from app.profassist.models import Approval

    result = await approve_draft(db, org.id, user.id, draft_id)
    release = release_feedback(str(user.id), str(result.get("group_name") or ""))
    audit = release.get("audit") or {}
    db.add(
        Approval(
            organization_id=org.id,
            user_id=user.id,
            target_type=audit.get("target_type") or "grade_feedback",
            target_id=str(draft_id),
            action=audit.get("action") or "approved",
            note=audit.get("note") or release.get("message") or "",
        )
    )
    await db.flush()
    result["feedback_release"] = {
        "pushed": release.get("pushed"),
        "message": release.get("message"),
    }
    return result


@router.post("/drafts/{draft_id}/push")
async def draft_push(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await push_draft(db, org.id, user.id, draft_id)


@router.post("/courses/{course_id}/integrity/scan")
async def integrity_scan(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await scan_integrity(db, org.id, course_id, user.id)}


class IntegrityAction(BaseModel):
    course: str = "MAAI903"
    number: str = "1"
    left: str = "A"
    right: str = "B"
    action: str = "note"
    note: str = ""
    match_id: str = ""


class FeedbackBody(BaseModel):
    group: str = "Group A"
    course: str = "MAAI903"
    comments: list = Field(default_factory=list)
    rubric: list = Field(default_factory=list)
    overall: str = ""
    bank: list = Field(default_factory=list)
    overrides: dict = Field(default_factory=dict)


def _grade_place(course: str) -> tuple[str, str]:
    from app.profassist.integrity_board import _norm
    from app.profassist.journey import assignment_number

    slug = _norm(course) or "MAAI903"
    return slug, assignment_number(slug)


def _feedback_text(notes: dict[str, Any]) -> str:
    parts = [str(notes.get("overall") or "")]
    for comment in notes.get("comments") or []:
        if isinstance(comment, dict):
            parts.append(" | ".join(str(value) for value in comment.values() if str(value).strip()))
        else:
            parts.append(str(comment))
    for row in notes.get("rubric") or []:
        if isinstance(row, dict):
            parts.append(" | ".join(str(value) for value in row.values() if str(value).strip()))
    return "\n".join(part for part in parts if part.strip())


@router.get("/integrity/overview")
async def integrity_overview(
    user: CurrentUser, org: ProfOrg, db: DBSession, course: str = "all"
) -> dict:
    from app.profassist.integrity_board import overview_db

    return await overview_db(db, org.id, user.id, course)


@router.get("/integrity/matrix")
async def integrity_matrix(
    user: CurrentUser, org: ProfOrg, db: DBSession, course: str, number: str
) -> dict:
    from app.profassist.integrity_board import assignment_matrix_db

    return await assignment_matrix_db(db, org.id, user.id, course, number)


@router.get("/integrity/pair")
async def integrity_pair(
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    course: str,
    number: str,
    left: str,
    right: str,
) -> dict:
    from app.profassist.integrity_board import pair_detail_db

    return await pair_detail_db(db, org.id, user.id, course, number, left, right)


@router.post("/integrity/pair")
async def integrity_pair_action(
    body: IntegrityAction, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.integrity_board import _pair_id
    from app.profassist.models import Approval

    if body.action not in {"ok", "flag", "note"}:
        return {"saved": False}
    row = Approval(
        organization_id=org.id,
        user_id=user.id,
        target_type="integrity_pair",
        target_id=_pair_id(body.course, body.number, body.left, body.right),
        action=body.action,
        note=body.note or "",
    )
    db.add(row)
    await db.flush()
    return {
        "saved": True,
        "action": body.action,
        "note": body.note,
        "message": "Saved for you. Nothing was sent to Moodle or to a student.",
    }


@router.post("/integrity/match")
async def integrity_match_action(
    body: IntegrityAction, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.integrity_board import _pair_id, pair_detail_db
    from app.profassist.integrity_docs import save_decision
    from app.profassist.models import Approval

    if body.action not in {"ok", "flag"} or not body.match_id:
        return {"saved": False}
    pair_id = _pair_id(body.course, body.number, body.left, body.right)
    save_decision(pair_id, body.match_id, body.action)
    db.add(
        Approval(
            organization_id=org.id,
            user_id=user.id,
            target_type="integrity_match",
            target_id=f"{pair_id}:{body.match_id}",
            action=body.action,
            note="",
        )
    )
    await db.flush()
    detail = await pair_detail_db(
        db, org.id, user.id, body.course, body.number, body.left, body.right
    )
    return {
        "saved": True,
        "decisions": detail.get("decisions"),
        "matches": detail.get("matches"),
        "message": "Saved for you. Nothing was sent to Moodle or to a student.",
    }


@router.get("/integrity/file")
async def integrity_file(
    _: CurrentUser, __: ProfOrg, course: str, number: str, group: str, which: str = "pdf"
) -> Response:
    from app.profassist.integrity_docs import file_bytes

    data, media, filename = file_bytes(course, number, group, which)
    if not data:
        return Response(status_code=404)
    disposition = "attachment" if which == "original" else "inline"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/grade/feedback")
async def grade_feedback(
    user: CurrentUser, group: str = "Group A", course: str = "MAAI903"
) -> dict:
    from app.profassist.grade_notes import load_feedback
    from app.profassist.integrity_docs import document_side

    slug, number = _grade_place(course)
    notes = load_feedback(str(user.id), group, slug, number)
    letter = group.replace("Group ", "").strip() or "A"
    return {**notes, "document": document_side(slug, number, letter)}


@router.post("/grade/feedback")
async def grade_feedback_save(
    body: FeedbackBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.grade_notes import load_feedback, save_feedback
    from app.profassist.integrity_docs import document_side
    from app.profassist.models import Approval

    slug, number = _grade_place(body.course)
    before = load_feedback(str(user.id), body.group, slug, number)
    notes = save_feedback(
        str(user.id),
        body.group,
        {
            "comments": body.comments,
            "rubric": body.rubric,
            "overall": body.overall,
            "bank": body.bank,
            "overrides": body.overrides,
        },
        slug,
        number,
    )
    db.add(
        Approval(
            organization_id=org.id,
            user_id=user.id,
            target_type="grade_feedback",
            target_id=body.group,
            action="saved",
            note="Private draft. Nothing was sent to Moodle or to a student.",
        )
    )
    await db.flush()
    await capture_movement(
        db,
        org.id,
        user.id,
        "feedback",
        _feedback_text(before),
        _feedback_text(notes),
        "grade-feedback",
    )
    letter = body.group.replace("Group ", "").strip() or "A"
    return {
        **notes,
        "document": document_side(slug, number, letter),
        "message": "Saved as a private draft. Nothing was sent to Moodle or to a student.",
    }


class SendGradeBody(BaseModel):
    group: str = "Group A"
    course: str = ""


@router.post("/grade/send")
async def grade_send(body: SendGradeBody, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    from app.profassist.journey import send_grade

    return await send_grade(db, org.id, user.id, body.course, body.group)


@router.get("/courses/{course_id}/integrity")
async def integrity(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_flags(db, org.id, course_id, user.id)}


@router.post("/integrity/{flag_id}")
async def integrity_update(
    flag_id: uuid.UUID, body: FlagBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await set_flag(db, org.id, user.id, flag_id, body.status)


@router.get("/courses/{course_id}/students")
async def students(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await list_students(db, org.id, course_id)


@router.get("/style")
async def style(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await get_style(db, org.id, user.id)


@router.put("/style")
async def style_save(body: TextBody, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await save_style(db, org.id, user.id, body.soul_md)


@router.put("/style/about")
async def style_about(body: AboutBody, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await save_about(db, org.id, user.id, body.about_md)


@router.post("/style/about/reset")
async def style_about_reset(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await reset_about(db, org.id, user.id)


@router.post("/style/template")
async def style_template(
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    file: UploadFile = File(...),
) -> dict:
    return await save_template(
        db, org.id, user.id, file.filename or "master.pptx", await file.read()
    )


@router.get("/reflections")
async def reflections(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_reflections(db, org.id, user.id)}


@router.post("/reflections/run")
async def reflections_run(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await run_reflection(db, org.id, user.id)


@router.post("/reflections/{reflection_id}/approve")
async def reflections_approve(
    reflection_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_reflection(db, org.id, user.id, reflection_id)


@router.get("/calibrator")
async def calibrator(user: CurrentUser, org: ProfOrg) -> dict:
    return calibrator_page()


@router.post("/courses/{course_id}/slides/studio")
async def slides_studio(
    course_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    week: int = Query(default=0),
    instructions: str = Query(default=""),
) -> dict:
    return await build_cited_deck(db, org.id, course_id, user.id, week, instructions)


@router.get("/memories")
async def memories(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {"items": await list_memories(db, org.id, user.id)}


@router.delete("/memories/{memory_id}")
async def memory_delete(
    memory_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    removed = await delete_memory(db, org.id, user.id, memory_id)
    return {"removed": removed}


class SettingsBody(BaseModel):
    chat_enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    base_url: str = ""
    debate_enabled: bool = True
    debate_threshold: int = 0
    debate_max_rounds: int = 1
    agent_models: dict[str, dict[str, str]] = Field(default_factory=dict)
    moodle_sync_paused: bool = False
    moodle_sync_minutes: int = 30
    moodle_nightly_enabled: bool = True
    moodle_nightly_hour: int = 2


class TestBody(BaseModel):
    provider: str
    model: str = ""


class PromptBody(BaseModel):
    agent: str
    body: str = Field(min_length=1)


class ToolBody(BaseModel):
    agent: str
    tool: str
    enabled: bool


@router.get("/admin/ai")
async def ai_admin(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await admin_view(db, org.id)


@router.put("/admin/ai")
async def ai_admin_save(
    body: SettingsBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    return await save_model_settings(
        db,
        org.id,
        user.id,
        body.chat_enabled,
        body.provider,
        body.model,
        body.base_url,
        body.debate_enabled,
        body.debate_threshold,
        body.debate_max_rounds,
        body.agent_models,
        body.moodle_sync_paused,
        body.moodle_sync_minutes,
        body.moodle_nightly_enabled,
        body.moodle_nightly_hour,
    )


@router.post("/admin/ai/test")
async def ai_test(body: TestBody, user: CurrentAppAdmin, org: ProfOrg) -> dict:
    del user, org
    from app.profassist.providers import test_connection

    return test_connection(body.provider, body.model)


@router.post("/admin/ai/prompts")
async def ai_prompt_save(
    body: PromptBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    return await save_prompt(db, org.id, user.id, body.agent, body.body)


@router.post("/admin/ai/tools")
async def ai_tool_save(body: ToolBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    return await set_tool(db, org.id, user.id, body.agent, body.tool, body.enabled)


@router.get("/admin/models")
async def models_admin(user: CurrentAppAdmin, org: ProfOrg) -> dict:
    del user, org
    return await list_registered_models_async()


class StepBody(BaseModel):
    step: str
    payload: dict = Field(default_factory=dict)
    message: str = ""


class InstructionBody(BaseModel):
    instructions: str = ""


class ChatBody(BaseModel):
    message: str = ""
    confirmed: bool = False
    pending_tool: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class AcceptBody(BaseModel):
    tasks: list = Field(default_factory=list)


class SuggestBody(BaseModel):
    lo_codes: list[str] = Field(default_factory=list)


@router.get("/outlines")
async def outlines(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return {
        "items": await list_outlines(db, org.id, user.id),
        "steps": list(STEPS),
    }


@router.post("/outlines")
async def outlines_start(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await start_outline(db, org.id, user.id)


@router.get("/outlines/{outline_id}")
async def outlines_get(
    outline_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    row = await get_outline(db, org.id, user.id, outline_id)
    from app.profassist.outline import _public

    return _public(row)


@router.put("/outlines/{outline_id}/step")
async def outlines_step(
    outline_id: uuid.UUID, body: StepBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await save_step(db, org.id, user.id, outline_id, body.step, body.payload)


@router.post("/outlines/{outline_id}/assist")
async def outlines_assist(
    outline_id: uuid.UUID, body: StepBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await assist_step(db, org.id, user.id, outline_id, body.step, body.message)


@router.put("/outlines/{outline_id}/instructions")
async def outlines_instructions(
    outline_id: uuid.UUID, body: InstructionBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await save_instructions(db, org.id, user.id, outline_id, body.instructions)


@router.get("/outlines/{outline_id}/materials")
async def outlines_files(
    outline_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await outline_context(db, org.id, user.id, outline_id)


@router.delete("/outlines/{outline_id}/materials/{material_id}")
async def outlines_remove_material(
    outline_id: uuid.UUID,
    material_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    return await remove_outline_material(db, org.id, user.id, outline_id, material_id)


@router.post("/outlines/{outline_id}/materials")
async def outlines_attach(
    outline_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    file: UploadFile = File(...),
) -> dict:
    return await attach_file(
        db, org.id, user.id, outline_id, file.filename or "notes.txt", await file.read()
    )


@router.post("/outlines/{outline_id}/finish")
async def outlines_finish(
    outline_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await finish_outline(db, org.id, user.id, outline_id)


@router.get("/outlines/{outline_id}/document")
async def outlines_document(
    outline_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession, kind: str = "pdf"
) -> Response:
    filename, data, media = await document_bytes(db, org.id, user.id, outline_id, kind)
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/outlines/{outline_id}/assessments/suggest")
async def outlines_suggest(
    outline_id: uuid.UUID, body: SuggestBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await suggest_assessments(db, org.id, user.id, outline_id, body.lo_codes)


@router.post("/outlines/{outline_id}/assessments/accept")
async def outlines_accept(
    outline_id: uuid.UUID, body: AcceptBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await accept_assessments(db, org.id, user.id, outline_id, body.tasks)


@router.get("/council/stream")
async def council_stream(
    user: CurrentUser, org: ProfOrg, scene: str = Query(default="grade")
) -> StreamingResponse:
    del user, org

    async def events():
        for event in script_for(scene):
            await asyncio.sleep(float(event.get("delay") or 0))
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


class ReviewBody(BaseModel):
    mode: str = "council"
    reviewer: str = "curriculum"


@router.post("/outlines/{outline_id}/review")
async def outlines_review(
    outline_id: uuid.UUID, body: ReviewBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await run_review(db, org.id, user.id, outline_id, mode=body.mode, reviewer=body.reviewer)


@router.post("/outlines/{outline_id}/reviews/{review_id}/apply")
async def outlines_apply(
    outline_id: uuid.UUID,
    review_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    finding_id: str = Query(...),
) -> dict:
    return await apply_review_fix(db, org.id, user.id, outline_id, review_id, finding_id)


class AssignmentBody(BaseModel):
    course_id: str
    number: str = "A1"
    title: str = ""
    weight: int = 0
    due: str = ""
    lo_codes: list[str] = Field(default_factory=list)
    outline_task_id: str = ""
    assessment_id: str = ""
    body: str = ""
    instructions: str = ""


class IdeasBody(BaseModel):
    ideas: list[dict] = Field(default_factory=list)


class GroupsBody(BaseModel):
    course_id: str
    groups: list[dict] = Field(default_factory=list)


@router.get("/assignments")
async def assignments_list(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {
        "items": await list_for_course(db, org.id, user.id, course_id),
        "summary": await assess_summary(db, org.id, user.id, course_id),
    }


@router.post("/assignments")
async def assignments_create(
    body: AssignmentBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    text = body.body or await draft_text(body.title, body.lo_codes, body.instructions)
    return await create_from_task(
        db,
        org.id,
        user.id,
        course_id=uuid.UUID(body.course_id),
        number=body.number,
        title=body.title,
        weight=body.weight,
        due=body.due,
        lo_codes=body.lo_codes,
        outline_task_id=body.outline_task_id,
        assessment_id=body.assessment_id,
        body=text,
    )


@router.get("/assignments/{assignment_id}")
async def assignments_get(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await assignment_view(db, org.id, user.id, assignment_id)


@router.post("/assignments/{assignment_id}/ideas")
async def assignments_ideas(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    current = await assignment_view(db, org.id, user.id, assignment_id)
    ideas = await propose_ideas(current["title"], current["body"], current["lo_codes"])
    return await save_ideas(db, org.id, user.id, assignment_id, ideas)


@router.put("/assignments/{assignment_id}/ideas")
async def assignments_ideas_save(
    assignment_id: uuid.UUID, body: IdeasBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await save_ideas(db, org.id, user.id, assignment_id, body.ideas)


@router.get("/courses/{course_id}/roster")
async def course_roster(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    del user
    return {"items": await roster(db, org.id, course_id)}


@router.put("/courses/{course_id}/groups")
async def course_groups(
    course_id: uuid.UUID, body: GroupsBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await save_groups(db, org.id, user.id, course_id, body.groups)}


@router.post("/assignments/{assignment_id}/allocate")
async def assignments_allocate(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await allocate(db, org.id, user.id, assignment_id)


@router.post("/assignments/{assignment_id}/exemplars")
async def assignments_exemplars(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await write_exemplars(db, org.id, user.id, assignment_id)


@router.post("/assignments/{assignment_id}/publish")
async def assignments_publish(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await publish_assignment(db, org.id, user.id, assignment_id)


@router.post("/assignments/{assignment_id}/class")
async def assignments_class(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.journey import form_class

    return await form_class(db, org.id, user.id, assignment_id)


@router.post("/assignments/{assignment_id}/receive")
async def assignments_receive(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.journey import receive_submissions

    return await receive_submissions(db, org.id, user.id, assignment_id)


@router.get("/assignments/{assignment_id}/submissions")
async def assignments_submissions(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await list_submissions(db, org.id, user.id, assignment_id)}


@router.get("/assignments/{assignment_id}/similarity")
async def assignments_similarity(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await similarity_report(db, org.id, user.id, assignment_id)


@router.get("/brand")
async def brand(user: CurrentUser, org: ProfOrg) -> dict:
    del user
    return {
        "name": org.name,
        "logo_url": org.avatar_url or "/brand/uowd-logo.svg",
    }


@router.get("/tools")
async def tools_view(user: CurrentUser, org: ProfOrg) -> dict:
    del user, org
    return {"items": tool_catalog()}


@router.post("/chat")
async def professor_chat(body: ChatBody, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await chat_turn(
        db,
        org.id,
        user.id,
        is_admin=bool(user.is_app_admin),
        message=body.message,
        confirmed=body.confirmed,
        pending_tool=body.pending_tool,
        context=body.context,
    )


@router.post("/chat/stream")
async def professor_chat_stream(
    body: ChatBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> StreamingResponse:
    payload = await chat_turn(
        db,
        org.id,
        user.id,
        is_admin=bool(user.is_app_admin),
        message=body.message,
        confirmed=body.confirmed,
        pending_tool=body.pending_tool,
        context=body.context,
    )

    async def events():
        for item in chat_stream_events(payload):
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n".encode()
            if item["event"] == "text":
                await asyncio.sleep(0.02)

    return StreamingResponse(events(), media_type="text/event-stream")
