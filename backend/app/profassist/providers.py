"""LiteLLM provider catalog. Keys are read from the environment and never stored."""

import os
from typing import Any

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
    "rubric_designer",
    "persona_evidence",
    "persona_strict",
    "persona_supportive",
    "feedback_writer",
    "integrity",
    "reflection",
    "slide_studio",
    "chat",
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


def generate(provider_id: str, model: str, messages: list[dict[str, str]], **kwargs: Any):
    """One LiteLLM call. A quota failure becomes a plain error, with no secret in it."""
    import time

    import litellm

    from app.profassist.errors import ProfassistError

    call = dict(kwargs)
    call.update(extra_kwargs(provider_id))
    if provider_id == "gemini":
        call["drop_params"] = True
    last: Exception | None = None
    for attempt in range(3):
        try:
            return litellm.completion(
                model=litellm_model(provider_id, model),
                messages=messages,
                **call,
            )
        except Exception as exc:
            last = exc
            text = str(exc)
            if "not supported" in text and "thinking" in text.lower() and "reasoning_effort" in call:
                call.pop("reasoning_effort", None)
                continue
            if "high demand" in text.lower() or "unavailable" in text.lower() or "503" in text:
                time.sleep(2 * (attempt + 1))
                continue
            if getattr(exc, "status_code", None) == 429 or "quota" in text.lower():
                raise ProfassistError(
                    429,
                    "The model provider is out of free quota for this model. Try again later or choose another model.",
                ) from None
            raise
    raise last if last else RuntimeError("The model did not answer.")


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
