"""Deck editing and one-slide assistance.

A deck stays a draft until the professor approves it. The model may change only
the slide it was asked about, and the number of slides is preserved unless the
request explicitly asks to add, insert, remove, delete, or merge slides.
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.profassist import llm
from app.profassist.deps import ProfOrg
from app.profassist.errors import ProfassistError
from app.profassist.models import SlideDeck
from app.profassist.observe import step_trace_url
from app.profassist.service import _owned, capture_movement, review_deck
from app.profassist.settings_admin import load_runtime
from app.profassist.slide_memory import remember_slide_edits

router = APIRouter()
logger = logging.getLogger(__name__)

APPROVED_DECK_LOCKED = "Approved decks stay as you approved them. Create a new deck to change it."
SOURCES_NOTE = "No new sources supplied. Do not invent sources."
RESIZE = re.compile(r"\b(add|insert|remove|delete|merge)\b", re.IGNORECASE)
SLIDES = re.compile(r"\bslides?\b", re.IGNORECASE)


class DeckSaveBody(BaseModel):
    """The professor's own edit. Omitted fields are left alone."""

    title: str | None = None
    slides: Any | None = None


class DeckAssistBody(BaseModel):
    message: str = ""
    slide_index: int | None = None


CITATION_KEYS = ("filename", "section", "quote", "chunk_id")


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return str(bullet.get("text") or "").strip()
    return str(bullet or "").strip()


def _slides_text(title: str, slides: Any) -> str:
    """Full deck content: title, every bullet, and speaker notes."""
    blocks = [str(title or "").strip()]
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        slide_title = str(slide.get("title") or "").strip()
        bullets = [_bullet_text(bullet) for bullet in slide.get("bullets") or []]
        bullets = [bullet for bullet in bullets if bullet]
        notes = str(slide.get("speaker_notes") or slide.get("notes") or "").strip()
        parts = [slide_title]
        if bullets:
            parts.append("Bullets: " + " | ".join(bullets))
        if notes:
            parts.append("Notes: " + notes)
        block = "\n".join(part for part in parts if part)
        if block:
            blocks.append(block)
    return "\n\n".join(block for block in blocks if block)


def _deck(row: SlideDeck) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "course_id": str(row.course_id),
        "title": row.title,
        "status": row.status,
        "week": row.week,
        "slides": row.slides or [],
        "instructions": row.instructions or "",
        "review": getattr(row, "review", None) or {},
        "review_trace_url": getattr(row, "review_trace_url", "") or "",
    }


def _clean_citation(value: Any, status: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProfassistError(status, "A bullet citation must be an object.")
    citation = {
        key: value[key] for key in CITATION_KEYS if key in value and value[key] not in (None, "")
    }
    return citation or None


def _clean_bullet(value: Any, status: int) -> str | dict[str, Any] | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if not isinstance(value, dict):
        raise ProfassistError(status, "Every bullet must be text or an object with text.")
    text = value.get("text")
    if not isinstance(text, str):
        raise ProfassistError(status, "Every bullet needs text.")
    text = text.strip()
    if not text:
        return None
    citation = _clean_citation(value.get("citation"), status)
    if citation:
        return {"text": text, "citation": citation}
    return text


def _clean_slide(value: Any, status: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfassistError(status, "Every slide must be an object.")
    title = value.get("title")
    bullets = value.get("bullets")
    notes = value.get("speaker_notes")
    if notes is None:
        notes = value.get("notes")
    if not isinstance(title, str):
        raise ProfassistError(status, "Every slide needs a text title.")
    if not isinstance(bullets, list):
        raise ProfassistError(status, "Every slide needs a list of text bullets.")
    if notes is not None and not isinstance(notes, str):
        raise ProfassistError(status, "Speaker notes must be text.")
    clean_bullets = [
        bullet for item in bullets if (bullet := _clean_bullet(item, status)) is not None
    ]
    slide: dict[str, Any] = {"title": title, "bullets": clean_bullets}
    if notes:
        slide["speaker_notes"] = notes
    # Keep the deck's own citation list and layout; only bullets and notes are
    # canonicalised here. Dropping them would erase what the reviewer cites.
    citations = value.get("citations")
    if isinstance(citations, list):
        slide["citations"] = citations
    if "layout" in value:
        slide["layout"] = value.get("layout")
    return slide


def _clean_slides(value: Any, status: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ProfassistError(status, "Slides must be a list.")
    return [_clean_slide(item, status) for item in value]


def _resizes(message: str) -> bool:
    """True only when the message names a change to the number of slides."""
    text = message or ""
    return bool(RESIZE.search(text) and SLIDES.search(text))


def _locked(row: SlideDeck) -> None:
    if row.status == "approved":
        raise ProfassistError(409, APPROVED_DECK_LOCKED)


async def _row(
    db: DBSession, org_id: uuid.UUID, user_id: uuid.UUID, deck_id: uuid.UUID
) -> SlideDeck:
    return await _owned(db, SlideDeck, org_id, deck_id, user_id)


@router.get("/slides/{deck_id}")
async def deck_get(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    return _deck(await _row(db, org.id, user.id, deck_id))


@router.put("/slides/{deck_id}")
async def deck_save(
    deck_id: uuid.UUID, body: DeckSaveBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    row = await _row(db, org.id, user.id, deck_id)
    _locked(row)
    before_slides = copy.deepcopy(list(row.slides or []))
    before_text = _slides_text(row.title, row.slides)
    if body.title is not None:
        row.title = body.title
    if body.slides is not None:
        row.slides = _clean_slides(body.slides, 400)
    row.storage_key = ""
    after_text = _slides_text(row.title, row.slides)
    content_changed = before_text != after_text
    if content_changed:
        # The review described the old content; never let it look passed.
        row.review = {}
        row.review_trace_url = ""
    await db.flush()
    after_slides = list(row.slides or [])
    if content_changed:
        await capture_movement(db, org.id, user.id, "slides", before_text, after_text, "deck-save")
    if before_slides != after_slides:
        try:
            await remember_slide_edits(
                db, org.id, user.id, before_slides, after_slides, "deck-save"
            )
        except Exception:
            logger.info("Slide memory not captured; the deck save stands")
    return _deck(row)


@router.post("/slides/{deck_id}/review")
async def deck_review(
    deck_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    """Review the deck. The professor decides whether to change anything."""
    return await review_deck(db, org, user, deck_id)


@router.post("/slides/{deck_id}/assist")
async def deck_assist(
    deck_id: uuid.UUID, body: DeckAssistBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    row = await _row(db, org.id, user.id, deck_id)
    _locked(row)
    before_text = _slides_text(row.title, row.slides)
    current = list(row.slides or [])
    if body.slide_index is not None and not 0 <= body.slide_index < len(current):
        raise ProfassistError(400, "That slide is not in this deck.")

    await load_runtime(db, org.id, user.id)
    payload: dict[str, Any] = {
        "title": row.title,
        "slides": current,
        "existing_deck": _deck(row),
        "message": body.message,
        "instructions": row.instructions or "",
        "sources_note": SOURCES_NOTE,
    }
    if body.slide_index is not None:
        payload["slide_index"] = body.slide_index

    drafted = llm.complete("slides", payload)
    if not isinstance(drafted, dict):
        raise ProfassistError(422, "The model did not return a deck.")

    reply = str(drafted.get("reply") or "")
    raw_slides = drafted.get("slides")
    model_slides = _clean_slides(raw_slides, 422) if raw_slides is not None else None
    new_title = row.title
    if body.slide_index is None:
        raw_title = drafted.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            new_title = raw_title.strip()

    updated = current
    if model_slides is not None:
        if body.slide_index is not None:
            if model_slides:
                updated = list(current)
                # A full deck maps by index; a single revised slide is the replacement.
                replacement = (
                    model_slides[body.slide_index]
                    if len(model_slides) == len(current)
                    else model_slides[0]
                )
                updated[body.slide_index] = replacement
        elif _resizes(body.message):
            updated = model_slides
        else:
            updated = [
                model_slides[index] if index < len(model_slides) else current[index]
                for index in range(len(current))
            ]

    changed = [
        index
        for index, slide in enumerate(updated)
        if index >= len(current) or slide != current[index]
    ]
    slides_changed = updated != current
    title_changed = new_title != row.title
    if slides_changed:
        row.slides = updated
    if title_changed:
        row.title = new_title
    if slides_changed or title_changed:
        row.storage_key = ""
        after_text = _slides_text(row.title, row.slides)
        content_changed = after_text != before_text
        if content_changed:
            # The review described the old content; never let it look passed.
            row.review = {}
            row.review_trace_url = ""
        await db.flush()
        if content_changed:
            await capture_movement(
                db, org.id, user.id, "slides", before_text, after_text, "deck-assist"
            )
    return {
        "reply": reply,
        "deck": _deck(row),
        "changed_slides": changed,
        "trace_url": step_trace_url() or "",
    }
