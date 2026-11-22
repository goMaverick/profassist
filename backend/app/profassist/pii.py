"""Remove names, emails, phones and student IDs before any model call.

This is a local stand-in for Presidio. The mapping stays in Postgres and is
never sent to the model. A document is quarantined when a personal-data
pattern is still present after replacement.
"""

import re
from dataclasses import dataclass, field

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
}


@dataclass
class ScrubResult:
    text: str
    replacements: list[dict[str, str]] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    quarantined: bool = False


def _token(kind: str, number: int) -> str:
    return f"[{kind}_{number}]"


def _presidio_extra(text: str) -> list[tuple[str, str]]:
    """Presidio pattern pass. Falls back quietly when the package is absent."""
    try:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
        from presidio_analyzer.nlp_engine import NlpEngine
        from presidio_anonymizer import AnonymizerEngine
    except Exception:
        return []

    class _NoNlp(NlpEngine):
        def load(self) -> None:
            return None

        def is_loaded(self) -> bool:
            return True

        def process_text(self, text: str, language: str) -> dict:
            return {}

        def process_batch(self, texts, language: str, **kwargs):
            return [{} for _ in texts]

        def is_stopword(self, word: str, language: str) -> bool:
            return False

        def is_punct(self, text: str, language: str) -> bool:
            return False

        def get_supported_entities(self) -> list[str]:
            return []

        def get_supported_languages(self) -> list[str]:
            return ["en"]

    try:
        email = PatternRecognizer(
            supported_entity="EMAIL_ADDRESS",
            patterns=[Pattern("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", 0.8)],
        )
        sid = PatternRecognizer(
            supported_entity="STUDENT_ID",
            patterns=[Pattern("sid", r"\b\d{7,10}\b", 0.6)],
        )
        engine = AnalyzerEngine(nlp_engine=_NoNlp(), registry=None, supported_languages=["en"])
        engine.registry.add_recognizer(email)
        engine.registry.add_recognizer(sid)
        findings = engine.analyze(text=text, language="en")
        anonymized = AnonymizerEngine().anonymize(text=text, analyzer_results=findings)
        if anonymized.text == text:
            return []
        return [("PRESIDIO", anonymized.text)]
    except Exception:
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

    for match in re.finditer(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b", result.text):
        first, second = match.group(1), match.group(2)
        if first.lower() in SAFE_WORDS or second.lower() in SAFE_WORDS:
            continue
        if any(part.lower() in SAFE_WORDS for part in (first, second)):
            continue
        result.uncertain.append(f"{first} {second}")

    extra = _presidio_extra(result.text)
    if extra:
        result.text = extra[0][1]
        result.replacements.append({"token": "[PRESIDIO]", "value": "redacted", "kind": "PRESIDIO"})
    result.quarantined = bool(result.uncertain)
    return result


def assert_prompt_is_clean(prompt: str) -> None:
    """Last gate in front of the model. Refuses the call instead of guessing."""
    if EMAIL_RE.search(prompt or "") or BARE_ID_RE.search(prompt or ""):
        raise RuntimeError("Refusing the model call: an email or ID is still in the prompt.")
