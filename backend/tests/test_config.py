"""Key resolution for the LLM gateway.

A POC deploy ships with one Gemini key. That key must reach both LiteLLM and
Mem0, without an extra neutral LLM_API_KEY aliasing step.
"""

import pytest

from app.profassist import config, memory

KEY_NAMES = ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_no_key_is_empty() -> None:
    assert config.llm_api_key() == ""


@pytest.mark.parametrize("name", KEY_NAMES)
def test_any_supported_key_is_used(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "test-key")
    assert config.llm_api_key() == "test-key"


def test_neutral_keys_win_over_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "google")
    monkeypatch.setenv("OPENAI_API_KEY", "openai")
    monkeypatch.setenv("LLM_API_KEY", "llm")
    assert config.llm_api_key() == "llm"

    monkeypatch.delenv("LLM_API_KEY")
    assert config.llm_api_key() == "openai"

    monkeypatch.delenv("OPENAI_API_KEY")
    assert config.llm_api_key() == "gemini"


def test_gemini_key_reaches_the_mem0_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mem0 is enabled in Compose; it must work with only GEMINI_API_KEY set."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("MEM0_EMBEDDER_PROVIDER", "fastembed")
    monkeypatch.setenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("MEM0_EMBEDDER_DIMS", "384")

    mem0_config = memory._mem0_config()

    assert mem0_config is not None
    assert mem0_config["llm"]["config"]["api_key"] == "test-key"
