"""Professor API. Drafts stay drafts until she approves them."""

import uuid

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.profassist.deps import ProfOrg
from app.profassist.moodle import get_connector
from app.profassist.service import (
    add_material,
    approve_assessment,
    approve_deck,
    approve_draft,
    approve_objective,
    approve_reflection,
    calibrator_page,
    deck_bytes,
    draft_assessment,
    draft_objectives,
    draft_slides,
    edit_draft,
    get_assessment,
    get_draft,
    get_style,
    get_submission,
    grade_queue,
    home,
    list_courses,
    list_decks,
    list_flags,
    list_materials,
    list_objectives,
    list_reflections,
    list_students,
    push_draft,
    push_record,
    reveal_draft,
    run_grade,
    run_reflection,
    save_style,
    scan_integrity,
    set_flag,
    sync_moodle,
)

router = APIRouter()


class TextBody(BaseModel):
    soul_md: str = Field(min_length=1)


class EditBody(BaseModel):
    overall_feedback: str = ""
    levels: dict[str, str] = Field(default_factory=dict)


class FlagBody(BaseModel):
    status: str


class LaunchBody(BaseModel):
    claims: dict = Field(default_factory=dict)


@router.get("/home")
async def home_view(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await home(db, org.id)


@router.get("/courses")
async def courses(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"items": await list_courses(db, org.id)}


@router.post("/moodle/sync")
async def moodle_sync(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await sync_moodle(db, org.id)


@router.post("/lti/launch")
async def lti_launch(body: LaunchBody, user: CurrentUser, org: ProfOrg) -> dict:
    del user, org
    return get_connector().lti_launch(body.claims)


@router.get("/courses/{course_id}/materials")
async def materials(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"items": await list_materials(db, org.id, course_id)}


@router.post("/courses/{course_id}/materials")
async def upload_material(
    course_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    file: UploadFile = File(...),
) -> dict:
    del user
    data = await file.read()
    return await add_material(db, org.id, course_id, file.filename or "notes.txt", data)


@router.post("/courses/{course_id}/objectives/draft")
async def objectives_draft(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await draft_objectives(db, org.id, course_id, user.id)}


@router.get("/courses/{course_id}/objectives")
async def objectives(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"items": await list_objectives(db, org.id, course_id)}


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
    del user
    return {"items": await list_decks(db, org.id, course_id)}


@router.post("/slides/{deck_id}/approve")
async def slides_approve(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_deck(db, org.id, user.id, deck_id)


@router.get("/slides/{deck_id}/pptx")
async def slides_pptx(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> Response:
    del user
    filename, data = await deck_bytes(db, org.id, deck_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/courses/{course_id}/assessment/draft")
async def assessment_draft(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await draft_assessment(db, org.id, course_id, user.id)


@router.get("/courses/{course_id}/assessment")
async def assessment(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"assessment": await get_assessment(db, org.id, course_id)}


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
    del user
    return await grade_queue(db, org.id, course_id)


@router.get("/submissions/{submission_id}")
async def submission(
    submission_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    del user
    return await get_submission(db, org.id, submission_id)


@router.post("/submissions/{submission_id}/grade")
async def grade_one(
    submission_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await run_grade(db, org.id, user.id, submission_id)


@router.get("/drafts/{draft_id}")
async def draft(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await get_draft(db, org.id, draft_id)


@router.post("/drafts/{draft_id}/reveal")
async def draft_reveal(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await reveal_draft(db, org.id, user.id, draft_id)


@router.post("/drafts/{draft_id}/edit")
async def draft_edit(
    draft_id: uuid.UUID, body: EditBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    del user
    return await edit_draft(db, org.id, draft_id, body.overall_feedback, body.levels)


@router.post("/drafts/{draft_id}/approve")
async def draft_approve(
    draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_draft(db, org.id, user.id, draft_id)


@router.post("/drafts/{draft_id}/push")
async def draft_push(draft_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await push_draft(db, org.id, user.id, draft_id)


@router.post("/courses/{course_id}/integrity/scan")
async def integrity_scan(
    course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    del user
    return {"items": await scan_integrity(db, org.id, course_id)}


@router.get("/courses/{course_id}/integrity")
async def integrity(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"items": await list_flags(db, org.id, course_id)}


@router.post("/integrity/{flag_id}")
async def integrity_update(
    flag_id: uuid.UUID, body: FlagBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await set_flag(db, org.id, user.id, flag_id, body.status)


@router.get("/courses/{course_id}/students")
async def students(course_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await list_students(db, org.id, course_id)


@router.get("/style")
async def style(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await get_style(db, org.id, user.id)


@router.put("/style")
async def style_save(body: TextBody, user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    return await save_style(db, org.id, user.id, body.soul_md)


@router.get("/reflections")
async def reflections(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"items": await list_reflections(db, org.id)}


@router.post("/reflections/run")
async def reflections_run(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await run_reflection(db, org.id)


@router.post("/reflections/{reflection_id}/approve")
async def reflections_approve(
    reflection_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await approve_reflection(db, org.id, user.id, reflection_id)


@router.get("/calibrator")
async def calibrator(user: CurrentUser, org: ProfOrg) -> dict:
    del user, org
    return calibrator_page()
