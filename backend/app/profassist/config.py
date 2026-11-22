"""Runtime settings that are safe to leave empty in the demo."""

import os


def _flag(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def llm_api_key() -> str:
    return _flag("LLM_API_KEY") or _flag("OPENAI_API_KEY")


def llm_model() -> str:
    return _flag("LLM_MODEL") or "gpt-4o-mini"


def llm_base_url() -> str | None:
    return _flag("LLM_BASE_URL") or None


def council_models() -> list[str]:
    raw = _flag("LLM_COUNCIL_MODELS")
    if not raw:
        model = llm_model()
        return [model, model, model]
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) == 1:
        return [parts[0], parts[0], parts[0]]
    while len(parts) < 3:
        parts.append(parts[-1])
    return parts[:3]


def moodle_mode() -> str:
    mode = (_flag("MOODLE_MODE") or "fake").lower()
    if mode not in {"fake", "real"}:
        return "fake"
    return mode


def langfuse_enabled() -> bool:
    return bool(_flag("LANGFUSE_PUBLIC_KEY")) and _flag("LANGFUSE_ENABLED").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def demo_email() -> str:
    return _flag("DEMO_PROFESSOR_EMAIL") or "professor@demo.uowd.ac.ae"


def demo_password() -> str:
    return _flag("DEMO_PROFESSOR_PASSWORD") or "ProfAssist-demo-1"


def auto_seed() -> bool:
    return _flag("PROFASSIST_AUTO_SEED").lower() in {"1", "true", "yes"}
