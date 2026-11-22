"""Load a SKILL.md plus the tool names it declares."""

from pathlib import Path


def skill_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "skills" / name / "SKILL.md"


def load_skill(name: str) -> dict[str, str | list[str]]:
    path = skill_path(name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    tools: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- `") and "`" in stripped[3:]:
            tools.append(stripped.split("`", 2)[1])
    return {"name": name, "instructions": text, "tools": tools}
