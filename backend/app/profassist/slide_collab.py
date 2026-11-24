"""Material Studio collaboration: a Creator drafts, a Reviewer checks.

The loop is deliberately small. The Creator applies structural fixes only:
titles, bullet count, bullet length, citations that already exist in the course
notes, and duplicate titles. It never invents a sentence or a source. The
Reviewer is the existing slide review graph. The loop stops on a pass, a pause,
two repair rounds, or when nothing can be repaired without inventing content.
"""

from __future__ import annotations

import asyncio
import copy
import re
import threading
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist import agents, service
from app.profassist.course_context import ready_chunks
from app.profassist.errors import ProfassistError
from app.profassist.models import SlideDeck
from app.profassist.rag import keyword_score

JOB_TTL_MINUTES = 30
MAX_REPAIR_ROUNDS = 2
MESSAGE_PAUSE = 0.35
MAX_BULLETS = 3
MAX_BULLET_CHARS = 220
MATCH_RATIO = 0.5
GAP_NOTE = "Gap: the notes do not cover this."
PAUSED_TEXT = "Paused. I am keeping the current draft as-is."
STRUCTURAL_CODES = frozenset(
    {"missing_title", "too_many_bullets", "long_bullet", "missing_citation", "duplicate_title"}
)
FILENAME = re.compile(r"[A-Za-z0-9_.-]+\.(?:pdf|docx|pptx|potx|txt|md|html?)\b", re.IGNORECASE)

# The registry is process-local on purpose: a collaboration job is a few seconds
# of streaming UI, not a durable queue. Jobs older than JOB_TTL_MINUTES are
# dropped on the next registry touch.
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _ident(value: Any) -> uuid.UUID:
    """Accept a UUID, an id string, or an object that carries ``.id``."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(getattr(value, "id", value)))


def _now() -> datetime:
    return datetime.now(UTC)


def cleanup_jobs(now: datetime | None = None) -> int:
    """Drop jobs older than thirty minutes. Returns how many were removed."""
    moment = now or _now()
    with _LOCK:
        stale = [
            job_id
            for job_id, job in _JOBS.items()
            if moment - job["created"] > timedelta(minutes=JOB_TTL_MINUTES)
        ]
        for job_id in stale:
            _JOBS.pop(job_id, None)
    return len(stale)


def create_job(org: Any, user: Any, course: Any, week: int = 0, instructions: str = "") -> str:
    cleanup_jobs()
    job_id = str(uuid.uuid4())
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "org_id": _ident(org),
            "user_id": _ident(user),
            "course_id": _ident(course),
            "week": int(week or 0),
            "instructions": str(instructions or ""),
            "stop": False,
            "started": False,
            "done": False,
            "deck_id": "",
            "created": _now(),
        }
    return job_id


def get_job(job_id: str, org: Any, user: Any) -> dict[str, Any]:
    """Return one job for its own org and user. A foreign job is a 404."""
    cleanup_jobs()
    with _LOCK:
        job = _JOBS.get(str(job_id))
    if job is None or job["org_id"] != _ident(org) or job["user_id"] != _ident(user):
        raise ProfassistError(404, "Collaboration job not found")
    return job


def pause_job(job_id: str, org: Any, user: Any) -> dict[str, Any]:
    job = get_job(job_id, org, user)
    with _LOCK:
        job["stop"] = True
    return job


def finish_job(job_id: str, org: Any, user: Any, deck_id: Any = None) -> dict[str, Any]:
    job = get_job(job_id, org, user)
    with _LOCK:
        job["done"] = True
        if deck_id:
            job["deck_id"] = str(deck_id)
    return job


# Reads and writes of a live job go through _LOCK. The stream, pause, and status
# routes can run on different threads of one process, and the GIL only makes a
# single dict read atomic -- it does not make "check then set" atomic. These
# small accessors keep that critical section in one place.
def _claim_job(job: dict[str, Any]) -> bool:
    """Mark the job started exactly once. True means this caller runs the loop."""
    with _LOCK:
        if job.get("started"):
            return False
        job["started"] = True
        return True


def _job_deck_id(job: dict[str, Any]) -> str:
    with _LOCK:
        return str(job.get("deck_id") or "")


def _job_stopped(job: dict[str, Any]) -> bool:
    with _LOCK:
        return bool(job.get("stop"))


def _set_job_deck_id(job: dict[str, Any], deck_id: Any) -> None:
    with _LOCK:
        job["deck_id"] = str(deck_id or "")


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return str(bullet.get("text") or "").strip()
    return str(bullet or "").strip()


def _has_citation(bullet: Any) -> bool:
    """A structured citation, or a source filename written on the slide."""
    if isinstance(bullet, dict):
        citation = bullet.get("citation")
        if isinstance(citation, dict) and (citation.get("filename") or citation.get("quote")):
            return True
        return bool(FILENAME.search(str(bullet.get("text") or "")))
    return bool(FILENAME.search(str(bullet or "")))


def _best_chunk(text: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The note passage that best supports a bullet, or None.

    A verbatim containment beats keyword overlap, and anything under
    MATCH_RATIO is treated as no support at all.
    """
    needle = text.casefold()
    best: dict[str, Any] | None = None
    best_score = 0.0
    for chunk in chunks:
        body = str(chunk.get("text") or "")
        if not body:
            continue
        if needle and needle in body.casefold():
            score = 1.0 + len(needle) / max(len(body), 1)
        else:
            score = keyword_score(text, body)
        if score > best_score:
            best, best_score = chunk, score
    if best is None or best_score < MATCH_RATIO:
        return None
    return best


def _quote(needle: str, body: str) -> str:
    """The passage around the bullet, kept verbatim. Never a rewritten quote."""
    text = " ".join(str(body or "").split())
    if not text:
        return ""
    found = text.casefold().find(needle.casefold()) if needle else -1
    if found < 0:
        return text[:240]
    start = max(0, found - 60)
    end = min(len(text), found + len(needle) + 60)
    return text[start:end]


def _citation(chunk: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "filename": str(chunk.get("filename") or "note"),
        "section": "note",
        "quote": _quote(text, str(chunk.get("text") or "")),
        "chunk_id": str(chunk.get("id") or ""),
    }


def _objectives(slides: list[Any]) -> list[str]:
    wanted: list[str] = []
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        objective = str(slide.get("objective") or "").strip()
        if objective:
            wanted.append(objective)
    return wanted


def repair_slides(
    slides: list[Any],
    chunks: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    objectives: list[str],
) -> tuple[list[Any], int, list[str]]:
    """Apply structural fixes only. Returns (slides, repaired, notes).

    The issue codes decide whether a structural pass is worth it at all. The
    fixes are then re-derived from the slides, so a capped or stale review can
    never make the Creator rewrite content that is already fine.
    """
    working = [copy.deepcopy(slide) for slide in slides or []]
    codes = {str(item.get("code") or "").strip() for item in issues or [] if isinstance(item, dict)}
    if codes and not codes & STRUCTURAL_CODES:
        return working, 0, []
    available = [chunk for chunk in chunks or [] if isinstance(chunk, dict)]
    wanted = [str(item).strip() for item in objectives or [] if str(item).strip()]
    repaired = 0
    notes: list[str] = []
    title_counts: dict[str, int] = {}
    for index, slide in enumerate(working):
        if not isinstance(slide, dict):
            continue
        label = f"Slide {index + 1}"
        title = str(slide.get("title") or "").strip()
        if not title:
            objective = str(slide.get("objective") or "").strip()
            if not objective and index < len(wanted):
                objective = wanted[index]
            slide["title"] = objective or "Untitled slide"
            repaired += 1
            notes.append(f"{label}: added a title.")
        key = " ".join(str(slide.get("title") or "").casefold().split())
        title_counts[key] = title_counts.get(key, 0) + 1
        if title_counts[key] > 1:
            slide["title"] = f"{str(slide.get('title') or '').strip()} ({title_counts[key]})"
            repaired += 1
            notes.append(f"{label}: made the duplicate title unique.")
        bullets = list(slide.get("bullets") or [])
        if len(bullets) > MAX_BULLETS:
            bullets = bullets[:MAX_BULLETS]
            repaired += 1
            notes.append(f"{label}: kept the first three bullets.")
        kept: list[Any] = []
        gap = False
        for bullet in bullets:
            text = _bullet_text(bullet)
            if not text:
                kept.append(copy.deepcopy(bullet))
                continue
            if len(text) > MAX_BULLET_CHARS:
                text = text[:MAX_BULLET_CHARS]
                repaired += 1
                notes.append(f"{label}: shortened a long bullet.")
            if _has_citation(bullet):
                if isinstance(bullet, dict):
                    row = dict(bullet)
                    row["text"] = text
                    kept.append(row)
                else:
                    kept.append(text)
                continue
            chunk = _best_chunk(text, available)
            if chunk is None:
                gap = True
                if isinstance(bullet, dict):
                    row = dict(bullet)
                    row["text"] = text
                    kept.append(row)
                else:
                    kept.append(text)
                continue
            citation = _citation(chunk, text)
            if isinstance(bullet, dict):
                row = dict(bullet)
                row["text"] = text
                row["citation"] = citation
            else:
                row = {"text": text, "citation": citation}
            kept.append(row)
            repaired += 1
            notes.append(f"{label}: attached a citation from {citation['filename']}.")
        slide["bullets"] = kept
        if gap and not slide.get("gap"):
            slide["gap"] = True
            slide["notes"] = GAP_NOTE
            repaired += 1
            notes.append(f"{label}: marked a gap; the notes do not cover a bullet.")
    return working, repaired, notes


def _slide_list(deck: dict[str, Any]) -> list[dict[str, Any]]:
    return [slide for slide in deck.get("slides") or [] if isinstance(slide, dict)]


def _message(role: str, text: str) -> dict[str, Any]:
    return {"type": "message", "role": role, "text": text}


async def _council_events(
    job: dict[str, Any], review: dict[str, Any]
) -> AsyncGenerator[dict[str, Any], None]:
    """Emit each reviewer pass, then the chair. A pause is checked before every emit."""
    for item in agents.review_messages(review):
        if _job_stopped(job):
            yield _message("creator", PAUSED_TEXT)
            return
        await asyncio.sleep(MESSAGE_PAUSE)
        role = str(item.get("role") or "reviewer")
        yield {"type": "typing", "role": role}
        if _job_stopped(job):
            yield _message("creator", PAUSED_TEXT)
            return
        await asyncio.sleep(MESSAGE_PAUSE)
        if _job_stopped(job):
            yield _message("creator", PAUSED_TEXT)
            return
        yield _message(role, str(item.get("text") or ""))


def _review_message(review: dict[str, Any]) -> str:
    verdict = str(review.get("verdict") or "revise")
    try:
        score = int(review.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    issues = [
        text
        for text in (
            str(item.get("issue") or "").strip()
            for item in review.get("issues") or []
            if isinstance(item, dict)
        )
        if text
    ][:3]
    message = f"I reviewed the draft: {verdict} with a score of {score}."
    if issues:
        return message + " Up to three issues: " + "; ".join(issues) + "."
    return message + " No issues found."


def _error_text(exc: Exception) -> str:
    """One honest line for the UI, trimmed to 300 characters."""
    if isinstance(exc, ProfassistError):
        text = str(exc.detail or "The collaboration stopped.")
    else:
        reason = str(exc).strip() or exc.__class__.__name__
        text = f"The collaboration stopped unexpectedly: {reason}"
    return " ".join(text.split())[:300]


def _deck_summary(row: Any) -> dict[str, Any]:
    """The trimmed deck the final event sends: no thumbnails, no base64 payload."""
    return {
        "id": str(row.id),
        "title": str(getattr(row, "title", "") or ""),
        "week": getattr(row, "week", 0),
        "status": str(getattr(row, "status", "") or ""),
        "review": getattr(row, "review", None) or {},
        "review_trace_url": str(getattr(row, "review_trace_url", "") or ""),
    }


async def _load_deck(db: AsyncSession, org_id: Any, user_id: Any, deck_id: str) -> Any:
    """Best-effort lookup of the job's deck. A miss is not fatal."""
    if not deck_id:
        return None
    try:
        return await service._owned(db, SlideDeck, org_id, uuid.UUID(str(deck_id)), user_id)
    except (ProfassistError, ValueError, TypeError):
        return None
    except Exception:
        return None


def _final_event(job: dict[str, Any], row: Any) -> dict[str, Any]:
    deck = _deck_summary(row) if row is not None else None
    review = deck["review"] if deck else {}
    return {
        "type": "final",
        "deck": deck,
        "review": review,
        "messages": agents.review_messages(review) if review else [],
        "trace_url": deck["review_trace_url"] if deck else "",
        "paused": _job_stopped(job),
        "job_id": job["id"],
    }


async def collaboration_events(
    job: dict[str, Any], db: AsyncSession
) -> AsyncGenerator[dict[str, Any], None]:
    """Creator drafts, Reviewer checks, Creator repairs. Real slides only.

    The loop is guarded end to end: an unexpected runtime failure becomes an
    ``error`` event followed by a ``final`` event with whatever deck already
    exists, and the job is always finished. A second stream for the same job (an
    EventSource reconnect) does not rebuild the deck; it replays the current
    state instead. ``asyncio.CancelledError`` is a BaseException, so a client
    disconnect still propagates normally.
    """
    org_id = job["org_id"]
    user_id = job["user_id"]
    if not _claim_job(job):
        row = await _load_deck(db, org_id, user_id, _job_deck_id(job))
        if row is None:
            yield {"type": "error", "text": "This collaboration is already running."}
        yield _final_event(job, row)
        return
    try:
        yield {
            "type": "start",
            "job_id": job["id"],
            "creator": "Creator",
            "reviewer": "Reviewer",
        }
        await asyncio.sleep(MESSAGE_PAUSE)
        yield {"type": "typing", "role": "creator"}
        await asyncio.sleep(MESSAGE_PAUSE)
        deck = await service.build_cited_deck(
            db,
            org_id,
            job["course_id"],
            user_id,
            job["week"],
            job["instructions"],
        )
        # Persist the draft before the first message: a pause or a dropped
        # connection must leave a saved deck, not an uncommitted one.
        await db.commit()
        if deck.get("id"):
            _set_job_deck_id(job, deck["id"])
        slides = _slide_list(deck)
        review = deck.get("review")
        if not isinstance(review, dict):
            review = {}
        objective_count = len(_objectives(slides)) or len(slides)
        yield _message(
            "creator",
            f"I drafted {len(slides)} slides from {objective_count} objectives and the course notes.",
        )
        # The build already produced the first review. If a pause arrived while
        # it was running, keep this draft and skip the council and repair rounds.
        if _job_stopped(job):
            yield _message("creator", PAUSED_TEXT)
            row = await _load_deck(db, org_id, user_id, _job_deck_id(job))
            yield _final_event(job, row)
            return
        async for event in _council_events(job, review):
            yield event
        if _job_stopped(job):
            row = await _load_deck(db, org_id, user_id, _job_deck_id(job))
            yield _final_event(job, row)
            return
        for _round in range(MAX_REPAIR_ROUNDS):
            await asyncio.sleep(MESSAGE_PAUSE)
            if _job_stopped(job):
                yield _message("creator", PAUSED_TEXT)
                break
            verdict = str(review.get("verdict") or "")
            try:
                score = int(review.get("score") or 0)
            except (TypeError, ValueError):
                score = 0
            if verdict == "pass" or score >= 85:
                break
            deck_id = _job_deck_id(job)
            if not deck_id:
                break
            try:
                row = await service._owned(db, SlideDeck, org_id, uuid.UUID(deck_id), user_id)
            except (ProfassistError, ValueError):
                break
            chunks = await ready_chunks(db, org_id, user_id, job["course_id"])
            repaired_slides, repaired, notes = repair_slides(
                list(row.slides or []),
                chunks,
                list(review.get("issues") or []),
                _objectives(list(row.slides or [])),
            )
            if repaired == 0:
                yield _message(
                    "creator",
                    "I cannot fix these without inventing content; I am leaving them as gaps.",
                )
                break
            row.slides = repaired_slides
            row.storage_key = ""
            # The stored review described the old slides. Clear it before the
            # repair is committed; review_deck below writes the fresh verdict.
            row.review = {}
            row.review_trace_url = ""
            await db.flush()
            # Persist the repair before reporting it, so a pause keeps it.
            await db.commit()
            yield _message("creator", f"I fixed {repaired} issues: " + "; ".join(notes[:6]))
            await asyncio.sleep(MESSAGE_PAUSE)
            result = await service.review_deck(db, org_id, user_id, uuid.UUID(deck_id))
            await db.commit()
            review = result.get("review")
            if not isinstance(review, dict):
                review = {}
            async for event in _council_events(job, review):
                yield event
            if _job_stopped(job):
                break
        row = await _load_deck(db, org_id, user_id, _job_deck_id(job))
        yield _final_event(job, row)
    except Exception as exc:
        yield {"type": "error", "text": _error_text(exc)}
        row = await _load_deck(db, org_id, user_id, _job_deck_id(job))
        yield _final_event(job, row)
    finally:
        finish_job(job["id"], org_id, user_id, _job_deck_id(job) or None)
