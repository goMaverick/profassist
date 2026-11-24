"""Runtime settings read from the environment."""

import os


def _flag(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def llm_api_key() -> str:
    """The key LiteLLM spends.

    A Gemini-only install is a supported single-key setup: the platform and Mem0
    both accept GEMINI_API_KEY (or GOOGLE_API_KEY) when no neutral key is set.
    """
    return (
        _flag("LLM_API_KEY")
        or _flag("OPENAI_API_KEY")
        or _flag("GEMINI_API_KEY")
        or _flag("GOOGLE_API_KEY")
    )


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


def moodle_push_enabled() -> bool:
    """Real grade write stays off until an admin sets this flag."""
    return _flag("MOODLE_PUSH_ENABLED").lower() in {"1", "true", "yes", "on"}


def moodle_mode() -> str:
    """``real`` unless MOODLE_MODE is explicitly ``fake`` (automated tests only)."""
    mode = (_flag("MOODLE_MODE") or "real").lower()
    return "fake" if mode == "fake" else "real"


def moodle_allow_private() -> bool:
    """Allow a local Moodle in development. Never on in production."""
    return _flag("MOODLE_ALLOW_PRIVATE").lower() in {"1", "true", "yes", "on"}


def moodle_base_url() -> str:
    """Environment fallback used only when an org has no connection row."""
    return _flag("MOODLE_BASE_URL").rstrip("/")


def moodle_ws_token() -> str:
    """Environment fallback used only when an org has no connection row."""
    return _flag("MOODLE_WS_TOKEN")


def langfuse_enabled() -> bool:
    return bool(_flag("LANGFUSE_PUBLIC_KEY")) and _flag("LANGFUSE_ENABLED").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
