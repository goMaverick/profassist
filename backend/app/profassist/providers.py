"""LiteLLM provider catalog. Keys are read from the environment and never stored."""

import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
_pace_lock = threading.Lock()
_last_gemini_call = 0.0

PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "label": "OpenAI",
        "env": ["OPENAI_API_KEY", "LLM_API_KEY"],
        "default_model": "gpt-4o-mini",
        "litellm_model": "openai/{model}",
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "env": ["ANTHROPIC_API_KEY"],
        "default_model": "claude-3-5-haiku-latest",
        "litellm_model": "anthropic/{model}",
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "default_model": "gemini-3.5-flash-lite",
        "litellm_model": "gemini/{model}",
    },
    {
        "id": "xai",
        "label": "xAI Grok",
        "env": ["XAI_API_KEY"],
        "default_model": "grok-2-latest",
        "litellm_model": "xai/{model}",
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "env": ["MISTRAL_API_KEY"],
        "default_model": "mistral-small-latest",
        "litellm_model": "mistral/{model}",
    },
    {
        "id": "azure",
        "label": "Azure OpenAI",
        "env": ["AZURE_API_KEY", "AZURE_API_BASE"],
        "default_model": "gpt-4o-mini",
        "litellm_model": "azure/{model}",
    },
    {
        "id": "bedrock",
        "label": "AWS Bedrock",
        "env": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "litellm_model": "bedrock/{model}",
    },
    {
        "id": "ollama",
        "label": "Ollama / local",
        "env": ["OLLAMA_API_BASE"],
        "default_model": "llama3.2",
        "litellm_model": "ollama/{model}",
    },
    {
        "id": "openai_compatible",
        "label": "OpenAI-compatible URL",
        "env": ["LLM_BASE_URL"],
        "default_model": "gpt-4o-mini",
        "litellm_model": "openai/{model}",
    },
]

AGENTS = [
    "course_designer",
    "document_analyst",
    "rubric_designer",
    "persona_evidence",
    "persona_strict",
    "persona_supportive",
    "feedback_writer",
    "integrity",
    "reflection",
    "slide_studio",
    "slide_reviewer",
    "assignment_reviewer",
    "chat",
    "chief_of_staff",
]


def _present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def provider_by_id(provider_id: str) -> dict[str, Any]:
    for provider in PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    return PROVIDERS[0]


def key_configured(provider_id: str) -> bool:
    provider = provider_by_id(provider_id)
    if provider_id == "azure":
        return _present("AZURE_API_KEY") and _present("AZURE_API_BASE")
    if provider_id == "bedrock":
        return _present("AWS_ACCESS_KEY_ID") and _present("AWS_SECRET_ACCESS_KEY")
    if provider_id == "openai_compatible":
        return _present("LLM_BASE_URL") and (_present("LLM_API_KEY") or _present("OPENAI_API_KEY"))
    if provider_id == "ollama":
        return _present("OLLAMA_API_BASE")
    return any(_present(name) for name in provider["env"])


def any_key_configured() -> bool:
    """True when at least one provider has the credentials it needs."""
    return any(key_configured(provider["id"]) for provider in PROVIDERS)


def catalog() -> list[dict[str, Any]]:
    rows = []
    for provider in PROVIDERS:
        rows.append(
            {
                "id": provider["id"],
                "label": provider["label"],
                "default_model": provider["default_model"],
                "configured": key_configured(provider["id"]),
                "env": provider["env"],
            }
        )
    return rows


def model_label(provider_id: str, model: str) -> str:
    """A name a professor can read. No key is included."""
    if not key_configured(provider_id):
        return "No model configured"
    name = (model or "").strip()
    if provider_id == "gemini":
        words = name.removeprefix("gemini/").removeprefix("gemini-").replace("-", " ")
        pretty = " ".join(
            part if part[:1].isdigit() else part.capitalize() for part in words.split()
        )
        return f"Gemini {pretty}".strip()
    return name or provider_id


def litellm_model(provider_id: str, model: str) -> str:
    provider = provider_by_id(provider_id)
    name = (model or provider["default_model"]).strip()
    if "/" in name:
        return name
    return str(provider["litellm_model"]).format(model=name)


def extra_kwargs(provider_id: str) -> dict[str, str]:
    if provider_id == "azure":
        kwargs = {}
        if os.getenv("AZURE_API_BASE"):
            kwargs["api_base"] = os.environ["AZURE_API_BASE"]
        if os.getenv("AZURE_API_VERSION"):
            kwargs["api_version"] = os.environ["AZURE_API_VERSION"]
        if os.getenv("AZURE_API_KEY"):
            kwargs["api_key"] = os.environ["AZURE_API_KEY"]
        return kwargs
    if provider_id == "openai_compatible":
        base = os.getenv("LLM_BASE_URL", "").strip()
        key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        kwargs = {}
        if base:
            kwargs["api_base"] = base
        if key:
            kwargs["api_key"] = key
        return kwargs
    if provider_id == "ollama":
        base = os.getenv("OLLAMA_API_BASE", "").strip()
        return {"api_base": base} if base else {}
    if provider_id == "gemini":
        # Gemini 3 spends the token budget on hidden reasoning unless this is set,
        # which cuts a chat answer off after a few words.
        return {"reasoning_effort": "minimal"}
    return {}


def _safe_detail(text: str) -> str:
    """Drop any configured secret before a message is shown on screen."""
    cleaned = text or ""
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "ANTHROPIC_API_KEY",
        "MOODLE_WS_TOKEN",
    ):
        secret = os.getenv(name, "")
        if secret:
            cleaned = cleaned.replace(secret, "hidden")
    return cleaned[:300]


def retry_wait(text: str) -> float | None:
    """How long a refused call is worth retrying.

    A short "retry in 12s" is the per-minute limit. A wait of more than a
    minute and a half, or a daily allowance that is already gone, should fail
    in one sentence instead of sitting there.
    """
    lowered = text.lower()
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", lowered)
    if match:
        delay = float(match.group(1))
        if delay > 90:
            return None
        return delay + 0.5
    if "per day" in lowered or "daily" in lowered or "limit: 0" in lowered:
        return None
    return 5.0


def _pace_gemini() -> None:
    """Keep a council from firing a dozen calls in the same second."""
    global _last_gemini_call
    with _pace_lock:
        wait = 2.5 - (time.monotonic() - _last_gemini_call)
        if wait > 0:
            time.sleep(wait)
        _last_gemini_call = time.monotonic()


_BUSY_MESSAGE = "The model is busy right now. Try again in a minute."
_QUOTA_MESSAGE = (
    "The model provider is out of quota for this model. Check the provider's usage limit, "
    "then try again later or choose another model in Settings."
)


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _is_quota(exc: Exception) -> bool:
    """A per-minute or daily allowance has run out."""
    text = str(exc).lower()
    return _status_code(exc) == 429 or "quota" in text or "resource_exhausted" in text


def _is_busy(exc: Exception) -> bool:
    """The provider is up but temporarily refusing work, usually with HTTP 503."""
    if _status_code(exc) == 429:
        return False
    from litellm.exceptions import ServiceUnavailableError

    if isinstance(exc, ServiceUnavailableError):
        return True
    text = str(exc).lower()
    return (
        _status_code(exc) == 503 or "high demand" in text or "unavailable" in text or "503" in text
    )


def generate(provider_id: str, model: str, messages: list[dict[str, Any]], **kwargs: Any):
    """One LiteLLM call. A quota failure becomes a plain error, with no secret in it."""
    import litellm

    from app.profassist.errors import ProfassistError

    call = dict(kwargs)
    call.update(extra_kwargs(provider_id))
    if provider_id == "gemini":
        call["drop_params"] = True
    last: Exception | None = None
    for attempt in range(4):
        try:
            if provider_id == "gemini":
                _pace_gemini()
            return litellm.completion(
                model=litellm_model(provider_id, model),
                messages=messages,
                **call,
            )
        except Exception as exc:
            last = exc
            text = str(exc)
            if (
                "not supported" in text
                and "thinking" in text.lower()
                and "reasoning_effort" in call
            ):
                call.pop("reasoning_effort", None)
                continue
            if _is_busy(exc):
                time.sleep(2 * (attempt + 1))
                continue
            if _is_quota(exc):
                wait = retry_wait(text)
                logger.warning(
                    "Model call refused (wait=%s): %s",
                    wait if wait is not None and attempt < 3 else "stop",
                    _safe_detail(text),
                )
                if wait is not None and attempt < 3:
                    time.sleep(wait)
                    continue
                raise ProfassistError(429, _QUOTA_MESSAGE) from None
            raise
    if last is None:
        raise RuntimeError("The model did not answer.")
    if _is_busy(last):
        logger.warning("Model stayed busy after retries: %s", _safe_detail(str(last)))
        raise ProfassistError(503, _BUSY_MESSAGE) from None
    if _is_quota(last):
        raise ProfassistError(429, _QUOTA_MESSAGE) from None
    raise last


def test_connection(provider_id: str, model: str) -> dict[str, Any]:
    """One short LiteLLM call. No key is written anywhere."""
    if provider_id == "ollama" and (not model or model == "llama3.2"):
        model = os.getenv("LLM_MODEL") or model or "llama3.2"
    if provider_id == "gemini" and model in {"", "gemini-2.0-flash", "gemini-2.5-flash"}:
        override = os.getenv("LLM_MODEL") or "gemini-3.5-flash-lite"
        model = override.split("/", 1)[-1]
    if not key_configured(provider_id):
        return {
            "ok": False,
            "configured": False,
            "detail": "No key is set for this provider. Add it as an environment variable and restart.",
        }
    try:
        response = generate(
            provider_id,
            model,
            [{"role": "user", "content": "Reply with the word ready."}],
            max_tokens=64,
            temperature=0,
        )
        text = response.choices[0].message.content or ""
        return {
            "ok": True,
            "configured": True,
            "detail": _safe_detail(text.strip() or "Connected."),
        }
    except Exception as exc:
        return {"ok": False, "configured": True, "detail": _safe_detail(str(exc))}
