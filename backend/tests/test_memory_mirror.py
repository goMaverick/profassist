"""Tests for the Postgres memory mirror and the Mem0 adapter."""

import logging
import os
import sys
import tempfile
import types
import uuid
from typing import Any

import pytest

from app.profassist import memory


class _FakeMemory:
    """Minimal stand-in for mem0.Memory."""

    configured: list[dict] = []
    added: list[tuple[str, str | None, dict | None]] = []
    searched: list[tuple[str, dict | None, int]] = []
    results: Any = []
    fail_on: str | None = None

    @classmethod
    def from_config(cls, config: dict) -> "_FakeMemory":
        cls.configured.append(config)
        if cls.fail_on == "config":
            raise RuntimeError("bad config")
        if cls.fail_on == "config_systemexit":
            raise SystemExit(1)
        return cls()

    def add(self, text: str, user_id: str | None = None, metadata: dict | None = None) -> None:
        if self.fail_on == "add":
            raise RuntimeError("write failed")
        if self.fail_on == "add_systemexit":
            # What spacy.cli.download raises when the model is missing.
            raise SystemExit(1)
        self.added.append((text, user_id, metadata))

    def search(self, query: str, *, filters: dict | None = None, top_k: int = 20) -> Any:
        if self.fail_on == "search":
            raise RuntimeError("search failed")
        if self.fail_on == "search_systemexit":
            raise SystemExit(1)
        self.searched.append((query, filters, top_k))
        return self.results


def _install_fake_mem0(monkeypatch: pytest.MonkeyPatch, *, fail_on: str | None = None):
    _FakeMemory.configured = []
    _FakeMemory.added = []
    _FakeMemory.searched = []
    _FakeMemory.results = []
    _FakeMemory.fail_on = fail_on
    module = types.ModuleType("mem0")
    module.Memory = _FakeMemory
    monkeypatch.setitem(sys.modules, "mem0", module)
    return _FakeMemory


def _install_empty_mem0(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mem0 module without Memory makes the import itself fail."""
    monkeypatch.setitem(sys.modules, "mem0", types.ModuleType("mem0"))


@pytest.fixture(autouse=True)
def _fresh_mem0(monkeypatch: pytest.MonkeyPatch):
    """No cached client and no inherited embedder settings between cases."""
    for name in (
        "MEM0_EMBEDDER_PROVIDER",
        "MEM0_EMBEDDER_MODEL",
        "MEM0_EMBEDDER_DIMS",
        "MEM0_HISTORY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    memory._reset_mem0_store()
    yield
    memory._reset_mem0_store()


def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")


def test_mem0_is_off_by_default_even_with_library_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("MEM0_ENABLED", raising=False)

    assert memory.mem0_enabled() is False
    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "short feedback") == []

    assert store.configured == []
    assert store.added == []


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True"])
def test_true_enables_the_mem0_write(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    store = _install_fake_mem0(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("MEM0_ENABLED", value)
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    assert memory.mem0_enabled() is True
    memory._mem0_add(str(org_id), str(user_id), "prefers short feedback")

    assert len(store.configured) == 1
    text, scoped_user, metadata = store.added[0]
    assert text == "prefers short feedback"
    assert scoped_user == memory.scope_id(org_id, user_id)
    assert metadata == {"organization_id": str(org_id), "owner_user_id": str(user_id)}


def test_other_flag_values_keep_mem0_off(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("MEM0_ENABLED", "yes")

    assert memory.mem0_enabled() is False
    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
    assert store.configured == []


def test_no_llm_key_keeps_mem0_off_even_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
    assert store.configured == []


def test_import_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_empty_mem0(monkeypatch)
    _enabled(monkeypatch)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "short feedback") == []


def test_config_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch, fail_on="config")
    _enabled(monkeypatch)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert len(store.configured) == 1
    assert store.added == []


def test_write_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch, fail_on="add")
    _enabled(monkeypatch)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert len(store.configured) == 1
    assert store.added == []


def test_a_system_exit_from_a_mem0_write_does_not_kill_the_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """mem0 downloads en_core_web_sm lazily and raises SystemExit when it cannot."""
    _install_fake_mem0(monkeypatch, fail_on="add_systemexit")
    _enabled(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.profassist.memory"):
        memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert "Mem0 write skipped (SystemExit)" in caplog.text


def test_a_system_exit_from_the_store_config_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mem0(monkeypatch, fail_on="config_systemexit")
    _enabled(monkeypatch)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
    assert memory._mem0_store() is None


def test_a_system_exit_from_a_mem0_search_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_mem0(monkeypatch, fail_on="search_systemexit")
    _enabled(monkeypatch)

    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets") == []


def test_mem0_search_filters_by_the_professor_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """mem0 2.2.1 rejects top-level entity kwargs; the scope belongs in filters."""
    store = _install_fake_mem0(monkeypatch)
    store.results = [{"memory": "Prefers shorter bullets"}, {"text": "Avoid exclamation marks"}]
    _enabled(monkeypatch)
    org_id, user_id = uuid.uuid4(), uuid.uuid4()

    found = memory.mem0_search(org_id, user_id, "shorter bullets", limit=3)

    assert found == ["Prefers shorter bullets", "Avoid exclamation marks"]
    assert store.searched == [("shorter bullets", {"user_id": f"{org_id}:{user_id}"}, 3)]


def test_mem0_search_never_leaks_another_professors_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    org_id, user_id = uuid.uuid4(), uuid.uuid4()

    memory.mem0_search(org_id, user_id, "bullets")

    scoped = store.searched[0][1]
    assert scoped == {"user_id": memory.scope_id(org_id, user_id)}
    assert str(uuid.uuid4()) not in scoped["user_id"]


def test_mem0_search_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_mem0(monkeypatch, fail_on="search")
    _enabled(monkeypatch)

    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets") == []


def test_mem0_search_ignores_a_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)

    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets", limit=0) == []
    assert store.configured == []


def test_telemetry_is_disabled_before_mem0_is_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)

    memory._disable_mem0_telemetry()

    assert os.environ["MEM0_TELEMETRY"] == "False"


def test_an_operator_can_opt_into_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEM0_TELEMETRY", "true")

    memory._disable_mem0_telemetry()

    assert os.environ["MEM0_TELEMETRY"] == "true"


def test_the_default_embedder_is_local_and_carries_no_openai_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this guards: an omitted embedder silently ships text to OpenAI."""
    store = _install_fake_mem0(monkeypatch)
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.internal/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-the-embedder")

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    embedder = store.configured[0]["embedder"]
    assert embedder == {"provider": "fastembed", "config": {"embedding_dims": 1024}}
    assert "api_key" not in embedder["config"]
    assert "openai_base_url" not in embedder["config"]
    assert store.configured[0]["vector_store"]["config"]["embedding_model_dims"] == 1024


def test_mem0_llm_points_at_the_configured_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without api_base, Mem0's LiteLLM provider calls api.openai.com by default."""
    _enabled(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.internal/v1")

    config = memory._mem0_config()

    assert config is not None
    assert config["llm"]["config"]["api_base"] == "https://llm.internal/v1"
    assert config["llm"]["config"]["api_key"] == "test-key"


def test_mem0_llm_omits_api_base_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _enabled(monkeypatch)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    config = memory._mem0_config()

    assert config is not None
    assert "api_base" not in config["llm"]["config"]


def test_a_cloud_embedder_is_used_only_when_named(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.internal/v1")
    monkeypatch.setenv("MEM0_EMBEDDER_PROVIDER", "openai")

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert store.configured[0]["embedder"] == {
        "provider": "openai",
        "config": {
            "embedding_dims": 1536,
            "api_key": "test-key",
            "openai_base_url": "https://llm.internal/v1",
        },
    }


def test_a_cloud_embedder_without_a_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Naming a cloud embedder is not enough: without a key the store is never built."""
    monkeypatch.setenv("MEM0_EMBEDDER_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with caplog.at_level(logging.INFO, logger="app.profassist.memory"):
        assert memory._mem0_config() is None

    assert "needs LLM_API_KEY" in caplog.text


def test_an_unsupported_embedder_skips_the_store(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    monkeypatch.setenv("MEM0_EMBEDDER_PROVIDER", "cohere")

    with caplog.at_level(logging.INFO, logger="app.profassist.memory"):
        memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")
        assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets") == []

    assert store.configured == []
    assert "unsupported MEM0_EMBEDDER_PROVIDER" in caplog.text


def test_a_custom_embedder_model_needs_its_dims(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    monkeypatch.setenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-small-en-v1.5")

    with caplog.at_level(logging.INFO, logger="app.profassist.memory"):
        memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert store.configured == []
    assert "MEM0_EMBEDDER_DIMS" in caplog.text


def test_a_custom_embedder_model_uses_the_declared_dims(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    monkeypatch.setenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("MEM0_EMBEDDER_DIMS", "384")

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert store.configured[0]["embedder"] == {
        "provider": "fastembed",
        "config": {"embedding_dims": 384, "model": "BAAI/bge-small-en-v1.5"},
    }
    assert store.configured[0]["vector_store"]["config"]["embedding_model_dims"] == 384


@pytest.mark.parametrize("raw", ["0", "-5", "wide"])
def test_bad_embedder_dims_are_skipped(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    monkeypatch.setenv("MEM0_EMBEDDER_DIMS", raw)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "prefers short feedback")

    assert store.configured == []


def test_one_store_is_built_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)
    org_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())

    memory._mem0_add(org_id, user_id, "one")
    memory._mem0_add(org_id, user_id, "two")
    memory.mem0_search(uuid.UUID(org_id), uuid.UUID(user_id), "three")

    assert len(store.configured) == 1
    assert [text for text, _, _ in store.added] == ["one", "two"]


def test_resetting_the_store_builds_a_new_client(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake_mem0(monkeypatch)
    _enabled(monkeypatch)

    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "one")
    memory._reset_mem0_store()
    memory._mem0_add(str(uuid.uuid4()), str(uuid.uuid4()), "two")

    assert len(store.configured) == 2


def test_history_path_stays_under_the_temp_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEM0_HISTORY_PATH", raising=False)

    path = memory._mem0_history_path()

    assert os.path.dirname(os.path.abspath(path)) == os.path.abspath(tempfile.gettempdir())
    assert path.endswith("profassist-mem0.db")


def test_a_configured_history_path_gets_its_parent_created(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    target = tmp_path / "nested" / "mem0" / "history.db"
    monkeypatch.setenv("MEM0_HISTORY_PATH", str(target))

    assert memory._mem0_history_path() == str(target)
    assert target.parent.is_dir()
