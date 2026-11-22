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
        "default_model": "gemini-2.0-flash",
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
    return {}


def test_connection(provider_id: str, model: str) -> dict[str, Any]:
    """One short LiteLLM call. No key is written anywhere."""
    if not key_configured(provider_id):
        return {
            "ok": False,
            "configured": False,
            "detail": "No key is set for this provider. Add it as an environment variable and restart.",
        }
    try:
        import litellm

        response = litellm.completion(
            model=litellm_model(provider_id, model),
            messages=[{"role": "user", "content": "Reply with the word ready."}],
            max_tokens=8,
            temperature=0,
            **extra_kwargs(provider_id),
        )
        text = response.choices[0].message.content or ""
        return {"ok": True, "configured": True, "detail": text.strip() or "Connected."}
    except Exception as exc:
        return {"ok": False, "configured": True, "detail": str(exc)[:300]}
