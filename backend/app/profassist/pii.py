"""Remove names, emails, phones and student IDs before any model call.

This is a local stand-in for Presidio. The mapping stays in Postgres and is
never sent to the model. A document is quarantined when a personal-data
pattern is still present after replacement.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]\d{3,4}\b")
STUDENT_ID_RE = re.compile(r"\b(?:student\s*id|sid|uowd)\s*[:#]?\s*([A-Z0-9\-]{5,})\b", re.I)
BARE_ID_RE = re.compile(r"\b\d{7,10}\b")
NAME_LABEL_RE = re.compile(
    r"\b(student|name|author|candidate)\b\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})"
)

# Words that look like a name only because a heading is in title case.
SAFE_WORDS = {
    "course",
    "learning",
    "outcome",
    "machine",
    "artificial",
    "intelligence",
    "design",
    "assessment",
    "rubric",
    "group",
    "report",
    "campus",
    "energy",
    "method",
    "findings",
    "introduction",
    "solutions",
    "model",
    "agent",
    "lecture",
    "note",
    "feedback",
    "level",
    "advanced",
    "beginning",
    "developing",
    "proficient",
    "united",
    "arab",
    "emirates",
    "personal",
    "data",
    "protection",
    "moodle",
    "professor",
    "university",
    "wollongong",
    "dubai",
    "main",
    "block",
    "library",
    "student",
    "hub",
    "weekly",
    "review",
    "practice",
    "term",
    "policies",
    "late",
    "work",
    "teaching",
    "schedule",
    "week",
    "topic",
    "session",
    "delivery",
    "submission",
    "requirements",
    "expectations",
    "resources",
    "weighting",
    "attendance",
    "participation",
}

# Two title-case words, optionally joined by a short name connector (``Al``).
_NAME_PAIR_RE = re.compile(
    r"\b([A-Z][a-z]{2,})"
    r"(?:\s+(?:Al|El|Bin|Bint|Ibn|Abu|Van|Von|Der|De|Da|Di))?"
    r"\s+([A-Z][a-z]{2,})\b"
)
_HEADING_MARKER_RE = re.compile(r"^\s*(?:(?:[#>]+|[-*\u2022])|\d+(?:\.\d+)*[.)])?\s*")
_COLON_LABEL_RE = re.compile(r"[A-Za-z0-9 &'\-]{1,40}:")
_HEADING_SMALL_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "vs",
}


@dataclass
class ScrubResult:
    text: str
    replacements: list[dict[str, str]] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    quarantined: bool = False


def _token(kind: str, number: int) -> str:
    return f"[{kind}_{number}]"


def _is_heading(text: str, start: int) -> bool:
    """A title-case pair that opens a heading line is not a person's name.

    A heading opens its line (after an optional bullet, number, or short
    ``Week 3:`` label), starts within the first 40 characters, and either fits
    in 60 characters or carries a colon. An academic heading word must anchor
    the line so a bare two-word name like ``Sara Maktoum`` is still a name.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    line = text[line_start : line_end if line_end >= 0 else len(text)]
    if start - line_start > 40:
        return False
    if len(line.strip()) > 60 and ":" not in line:
        return False
    prefix = text[line_start:start]
    marker = _HEADING_MARKER_RE.match(prefix)
    remainder = prefix[marker.end() :].strip() if marker else prefix.strip()
    if remainder and not _COLON_LABEL_RE.fullmatch(remainder):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", line)
    if not all(word[:1].isupper() or word.lower() in _HEADING_SMALL_WORDS for word in words):
        return False
    return any(word.lower() in SAFE_WORDS for word in words)


def _presidio_extra(text: str) -> list[tuple[str, str]]:
    """Presidio pattern pass. Falls back quietly when the package is absent."""
    try:
        from presidio_analyzer import (
            AnalyzerEngine,
            Pattern,
            PatternRecognizer,
            RecognizerRegistry,
        )
        from presidio_analyzer.nlp_engine import NoOpNlpEngine
        from presidio_anonymizer import AnonymizerEngine
    except Exception as exc:
        logger.warning("Presidio extra pass unavailable: %s", exc)
        return []

    try:
        # Presidio's own no-op engine: pattern recognizers need no NLP artifacts.
        nlp_engine = NoOpNlpEngine(models=[{"lang_code": "en", "model_name": "no_op"}])
        nlp_engine.load()
        email = PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            patterns=[Pattern("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", 0.8)],
        )
        sid = PatternRecognizer(
            supported_entity="STUDENT_ID",
            patterns=[Pattern("sid", r"\b\d{7,10}\b", 0.6)],
        )
        # Only these two recognizers run. A default registry would also add
        # URL and DRIVER_LICENSE patterns and rewrite filenames and links.
        registry = RecognizerRegistry()
        registry.add_recognizer(email)
        registry.add_recognizer(sid)
        engine = AnalyzerEngine(
            nlp_engine=nlp_engine, registry=registry, supported_languages=["en"]
        )
        findings = engine.analyze(text=text, language="en")
        anonymized = AnonymizerEngine().anonymize(text=text, analyzer_results=findings)
        if anonymized.text == text:
            return []
        return [("PRESIDIO", anonymized.text)]
    except Exception as exc:
        logger.warning("Presidio extra pass unavailable: %s", exc)
        return []


def scrub(text: str, known_names: list[str] | None = None) -> ScrubResult:
    """Replace personal data. Quarantine if some of it cannot be removed."""
    result = ScrubResult(text=text or "")
    counts = {"STUDENT": 0, "EMAIL": 0, "PHONE": 0, "ID": 0}

    def remember(kind: str, value: str) -> str:
        counts[kind] += 1
        token = _token(kind, counts[kind])
        result.replacements.append({"token": token, "value": value, "kind": kind})
        return token

    names = sorted(
        {name.strip() for name in (known_names or []) if name and name.strip()},
        key=len,
        reverse=True,
    )
    for name in names:
        pattern = re.compile(re.escape(name), re.I)
        result.text = pattern.sub(lambda match, n=name: remember("STUDENT", n), result.text)

    result.text = EMAIL_RE.sub(lambda match: remember("EMAIL", match.group(0)), result.text)
    result.text = PHONE_RE.sub(lambda match: remember("PHONE", match.group(0)), result.text)
    result.text = STUDENT_ID_RE.sub(
        lambda match: match.group(0).replace(match.group(1), remember("ID", match.group(1))),
        result.text,
    )
    result.text = BARE_ID_RE.sub(lambda match: remember("ID", match.group(0)), result.text)

    if EMAIL_RE.search(result.text) or BARE_ID_RE.search(result.text):
        result.uncertain.append("A contact detail or ID was still visible after scrubbing.")

    for match in NAME_LABEL_RE.finditer(result.text):
        candidate = match.group(2)
        if candidate.lower() not in {name.lower() for name in names}:
            result.uncertain.append(candidate)

    for match in _NAME_PAIR_RE.finditer(result.text):
        first, second = match.group(1), match.group(2)
        if first.lower() in SAFE_WORDS or second.lower() in SAFE_WORDS:
            continue
        if any(part.lower() in SAFE_WORDS for part in (first, second)):
            continue
        if _is_heading(result.text, match.start()):
            continue
        result.uncertain.append(match.group(0))

    extra = _presidio_extra(result.text)
    if extra:
        result.text = extra[0][1]
        result.replacements.append({"token": "[PRESIDIO]", "value": "redacted", "kind": "PRESIDIO"})
    result.quarantined = bool(result.uncertain)
    return result


def strip_contacts(text: str) -> str:
    """Remove emails, phones, and long IDs. Title-case course words stay."""
    text = EMAIL_RE.sub("[email removed]", text or "")
    text = PHONE_RE.sub("[phone removed]", text)
    return BARE_ID_RE.sub("[id removed]", text)


def strip_contacts_in_payload(value: Any) -> Any:
    """Scrub the string leaves of a JSON-shaped payload.

    Scrubbing the serialised text rewrites digits inside ``\\uXXXX`` escapes:
    ``\\u2013`` (an en dash) reads as a phone number, so the replacement leaves
    invalid JSON behind and the step save fails. Walking the structure keeps the
    escapes intact and still covers every string the user typed.
    """
    if isinstance(value, str):
        return strip_contacts(value)
    if isinstance(value, list):
        return [strip_contacts_in_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: strip_contacts_in_payload(item) for key, item in value.items()}
    return value


def assert_prompt_is_clean(prompt: str) -> None:
    """Last gate in front of the model. Refuses the call instead of guessing."""
    if EMAIL_RE.search(prompt or "") or BARE_ID_RE.search(prompt or ""):
        raise RuntimeError("Refusing the model call: an email or ID is still in the prompt.")
