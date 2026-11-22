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


def condense_about(soul: str, memories: list[dict], courses: list[str]) -> str:
    """One short portrait. Rewritten from what we know, not appended forever."""
    lines = ["About this professor:"]
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
    if courses:
        lines.append("Courses: " + ", ".join(courses[:8]))
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
    if not lessons:
        lessons.append(
            {
                "kind": kind or "preference",
                "text": f"For {kind or 'drafts'}, she changes the first draft before she approves it.",
            }
        )
    return lessons
