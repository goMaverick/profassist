"""Per-professor slide memory.

A slide edit is compared with the deck it came from. Only high-confidence style
lessons survive, so a one-off rewrite never becomes a permanent rule. Postgres
remains the source of truth. Mem0 is an optional recall mirror and never blocks.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist import memory
from app.profassist.models import ProfessorMemory
from app.profassist.rag import keyword_score

logger = logging.getLogger(__name__)

SLIDE_KINDS = ("slides", "tone", "preference")
ARTIFACT_KINDS = (
    "slides",
    "tone",
    "preference",
    "objective",
    "rubric",
    "feedback",
    "materials",
)
SHORTER_RATIO = 0.2
MAX_LESSONS = 3
_FILENAME = re.compile(r"[A-Za-z0-9_.-]+\.(?:pdf|docx|pptx|potx|txt|md|html?)\b", re.IGNORECASE)


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return " ".join(str(bullet.get("text") or "").split())
    return " ".join(str(bullet or "").split())


def _notes_of(slide: dict[str, Any]) -> str:
    return " ".join(str(slide.get("speaker_notes") or slide.get("notes") or "").split())


def slide_snapshot(slides: Any, title: str = "") -> str:
    """Deterministic text for a deck: title, every bullet, and speaker notes."""
    blocks = [str(title or "").strip()]
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        parts = [str(slide.get("title") or "").strip()]
        bullets = [_bullet_text(bullet) for bullet in slide.get("bullets") or []]
        bullets = [bullet for bullet in bullets if bullet]
        if bullets:
            parts.append("Bullets: " + " | ".join(bullets))
        notes = _notes_of(slide)
        if notes:
            parts.append("Notes: " + notes)
        block = "\n".join(part for part in parts if part)
        if block:
            blocks.append(block)
    return "\n\n".join(block for block in blocks if block)


def _structured(slides: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        bullets = [
            bullet for bullet in slide.get("bullets") or [] if isinstance(bullet, (str, dict))
        ]
        rows.append(
            {
                "title": str(slide.get("title") or "").strip(),
                "bullets": bullets,
                "notes": _notes_of(slide),
            }
        )
    return rows


def _has_citation(bullet: Any) -> bool:
    if isinstance(bullet, dict):
        citation = bullet.get("citation")
        if isinstance(citation, dict) and (citation.get("filename") or citation.get("quote")):
            return True
        return bool(_FILENAME.search(str(bullet.get("text") or "")))
    return bool(_FILENAME.search(str(bullet or "")))


def _average_bullets(slides: list[dict[str, Any]]) -> float:
    if not slides:
        return 0.0
    return sum(len(slide["bullets"]) for slide in slides) / len(slides)


def _average_bullet_length(slides: list[dict[str, Any]]) -> float:
    texts = [_bullet_text(bullet) for slide in slides for bullet in slide["bullets"]]
    texts = [text for text in texts if text]
    if not texts:
        return 0.0
    return sum(len(text) for text in texts) / len(texts)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]*", text or "")


def _capitalised_after_first(text: str) -> list[str]:
    """Words after the first that look like Title Case, not acronyms."""
    return [word for word in _words(text)[1:] if word[:1].isupper() and not word.isupper()]


def _is_sentence_case(text: str) -> bool:
    return len(_words(text)) >= 2 and not _capitalised_after_first(text)


def _is_title_case(text: str) -> bool:
    return bool(_capitalised_after_first(text)) and not _is_sentence_case(text)


def _title_lesson(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    for index in range(min(len(before), len(after))):
        old = before[index]["title"]
        new = after[index]["title"]
        if old and new and old != new and _is_title_case(old) and _is_sentence_case(new):
            return True
    return False


def extract_slide_lessons(before: Any, after: Any) -> list[str]:
    """High-confidence style lessons from a professor's own slide edit, max 3."""
    before_slides = _structured(before)
    after_slides = _structured(after)
    if before_slides == after_slides:
        return []

    lessons: list[str] = []
    if before_slides and after_slides:
        old_bullets = _average_bullets(before_slides)
        new_bullets = _average_bullets(after_slides)
        if new_bullets < old_bullets:
            lessons.append("Prefers fewer bullets per slide")
        elif new_bullets > old_bullets:
            lessons.append("Prefers more detail per slide")

        old_length = _average_bullet_length(before_slides)
        new_length = _average_bullet_length(after_slides)
        if old_length and new_length:
            change = (new_length - old_length) / old_length
            if change <= -SHORTER_RATIO:
                lessons.append(f"Prefers shorter bullets (about {round(new_length)} characters)")
            elif change >= SHORTER_RATIO:
                lessons.append(f"Prefers fuller bullet text (about {round(new_length)} characters)")

        old_citations = sum(
            1 for slide in before_slides for bullet in slide["bullets"] if _has_citation(bullet)
        )
        new_citations = sum(
            1 for slide in after_slides for bullet in slide["bullets"] if _has_citation(bullet)
        )
        if old_citations and not new_citations:
            lessons.append("Prefers citations in speaker notes, not on the slide")
        elif new_citations and not old_citations:
            lessons.append("Keep the source filename on the slide")

        old_notes = sum(1 for slide in before_slides if slide["notes"])
        new_notes = sum(1 for slide in after_slides if slide["notes"])
        if new_notes > old_notes:
            lessons.append("Adds speaker notes to explain the slide")

        if _title_lesson(before_slides, after_slides):
            lessons.append("Prefers sentence-case slide titles")

    if slide_snapshot(before).count("!") > slide_snapshot(after).count("!"):
        lessons.append("Avoid exclamation marks on slides")

    unique = list(dict.fromkeys(lessons))
    return unique[:MAX_LESSONS]


async def remember_slide_edits(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    before: Any,
    after: Any,
    source: str,
) -> list[str]:
    """Store each style lesson as slide memory. Mem0 mirrors inside remember()."""
    lessons = extract_slide_lessons(before, after)
    for lesson in lessons:
        await memory.remember(
            db,
            organization_id,
            user_id,
            lesson,
            kind="slides",
            source=source,
        )
    return lessons


def _recency(row: ProfessorMemory) -> float:
    created = getattr(row, "created_at", None)
    if isinstance(created, datetime):
        return created.timestamp()
    return 0.0


def _mem0_preferences(
    organization_id: uuid.UUID, user_id: uuid.UUID, query: str, limit: int
) -> list[str]:
    """Best-effort Mem0 recall. The Postgres copy is enough when it is off."""
    if not memory.mem0_enabled():
        return []
    try:
        import mem0  # noqa: F401

        return memory.mem0_search(organization_id, user_id, query, limit=limit)
    except Exception:
        logger.info("Mem0 recall skipped; stored slide preferences stand")
        return []


async def artifact_preferences(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    kinds: tuple[str, ...] | None = None,
    limit: int = 6,
) -> list[str]:
    """Artifact lessons of the chosen kinds, ranked by keyword overlap then recency."""
    if limit <= 0:
        return []
    allowed = tuple(kinds) if kinds is not None else ARTIFACT_KINDS
    result = await db.execute(
        select(ProfessorMemory)
        .where(
            ProfessorMemory.organization_id == organization_id,
            ProfessorMemory.owner_user_id == user_id,
        )
        .order_by(ProfessorMemory.created_at.desc())
    )
    rows = [
        row for row in result.scalars().all() if row.kind in allowed and str(row.text or "").strip()
    ]
    rows.sort(key=_recency, reverse=True)
    rows.sort(key=lambda row: keyword_score(query, str(row.text or "")), reverse=True)

    preferences: list[str] = []
    for row in rows:
        text = " ".join(str(row.text or "").split())
        if text and text not in preferences:
            preferences.append(text)
        if len(preferences) >= limit:
            break
    for extra in _mem0_preferences(organization_id, user_id, query, limit):
        text = " ".join(str(extra or "").split())
        if text and text not in preferences:
            preferences.append(text)
        if len(preferences) >= limit:
            break
    return preferences


async def slide_preferences(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[str]:
    """Slide, tone, and preference lessons, ranked by keyword overlap then recency."""
    return await artifact_preferences(
        db,
        organization_id,
        user_id,
        query,
        kinds=SLIDE_KINDS,
        limit=limit,
    )
