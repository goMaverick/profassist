"""Turn a professor's edit into a short lesson. No student names belong here."""

from app.profassist.similarity import tokens


def _overlap(left: str, right: str) -> float:
    a = set(tokens(left))
    b = set(tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def same_lesson(existing: str, new: str) -> bool:
    return _overlap(existing, new) >= 0.55


IDENTITY_PREFIXES = ("Professor:", "Teaches:")


def identity_lines(identity: dict | None) -> list[str]:
    """Name and title only. Never an email, never anything about a student."""
    identity = identity or {}
    name = str(identity.get("name") or "").strip()
    role = str(identity.get("role") or "").strip()
    lines: list[str] = []
    if name and role:
        lines.append(f"Professor: {name} — {role}")
    elif name:
        lines.append(f"Professor: {name}")
    elif role:
        lines.append(f"Professor: {role}")
    courses = [str(item).strip() for item in (identity.get("courses") or []) if str(item).strip()]
    if courses:
        lines.append("Teaches: " + ", ".join(courses[:8]))
    return lines


def split_identity(text: str) -> tuple[list[str], str]:
    """Separate the professor's identity lines from the scrubbed body."""
    identity: list[str] = []
    body: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith(IDENTITY_PREFIXES):
            identity.append(line)
        else:
            body.append(line)
    return identity, "\n".join(body)


def condense_about(
    soul: str,
    memories: list[dict],
    courses: list[str],
    identity: dict | None = None,
) -> str:
    """One short portrait. Rewritten from what we know, not appended forever."""
    lines = ["About this professor:"]
    lines.extend(identity_lines(identity))
    first = ""
    for line in (soul or "").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            first = line.strip()
            break
    if first:
        lines.append(first[:220])
    latest: dict[str, str] = {}
    for memory in memories:
        kind = memory.get("kind") or "preference"
        text = (memory.get("text") or "").strip()
        if text:
            latest[kind] = text[:220]
    for kind in (
        "tone",
        "strictness",
        "feedback",
        "rubric",
        "slides",
        "objectives",
        "style",
        "preference",
    ):
        if kind in latest:
            lines.append(f"{kind}: {latest[kind]}")
    fallback = [str(item).strip() for item in (courses or []) if str(item).strip()]
    taught = [
        str(item).strip() for item in ((identity or {}).get("courses") or []) if str(item).strip()
    ]
    if fallback and fallback[:8] != taught[:8]:
        lines.append("Courses: " + ", ".join(fallback[:8]))
    return "\n".join(lines)[:900]


def extract_lessons(kind: str, before: str, after: str) -> list[dict[str, str]]:
    """Compare an AI draft with what she kept. Identical text teaches nothing new."""
    original = (before or "").strip()
    final = (after or "").strip()
    if not final or original == final:
        return []
    lessons: list[dict[str, str]] = []
    if "!" in original and "!" not in final:
        lessons.append(
            {
                "kind": "tone",
                "text": "Write feedback without exclamation marks.",
            }
        )
    if kind == "grade" and len(final) < max(40, int(len(original) * 0.75)):
        lessons.append(
            {
                "kind": "feedback",
                "text": "Keep feedback shorter than the first draft.",
            }
        )
    if kind == "grade" and any(word in final.lower() for word in ("strict", "lower", "beginning")):
        lessons.append(
            {
                "kind": "strictness",
                "text": "She marks more strictly when the limitation is the main point.",
            }
        )
    if kind == "slides":
        lessons.append(
            {
                "kind": "slides",
                "text": "Prefer one idea per slide and keep the citation on the slide.",
            }
        )
    if kind == "rubric":
        lessons.append(
            {
                "kind": "rubric",
                "text": "Rubric levels should stay beginning, developing, proficient, and advanced.",
            }
        )
    if kind == "style":
        first = final.split("\n")[0][:180]
        lessons.append({"kind": "style", "text": f"Her style note: {first}"})
    if kind == "objective":
        lessons.append(
            {
                "kind": "objectives",
                "text": "Objectives should stay in the wording of the course notes.",
            }
        )
    if kind in {"outline", "assignment"} and original:
        if len(final) <= len(original) * 0.75:
            label = "outline" if kind == "outline" else "assignment brief"
            lessons.append({"kind": "objective", "text": f"Prefers a more concise {label}."})
        elif len(final) >= len(original) * 1.25:
            label = "outlines" if kind == "outline" else "assignment briefs"
            lessons.append({"kind": "objective", "text": f"Prefers fuller detail in {label}."})
    if not lessons:
        lessons.append(
            {
                "kind": kind or "preference",
                "text": f"For {kind or 'drafts'}, she changes the first draft before she approves it.",
            }
        )
    return lessons
