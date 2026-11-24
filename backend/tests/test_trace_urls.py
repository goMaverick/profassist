"""Model-step trace URLs stay top-level; artifact JSON stays clean."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

import app.profassist.llm as llm
import app.profassist.observe as observe
import app.profassist.outline_review as outline_review
import app.profassist.skills.slide_studio as slide_studio
from app.profassist.errors import ProfassistError

KEY_NAMES = (
    "OPENAI_API_KEY",
    "LLM_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "MISTRAL_API_KEY",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "OLLAMA_API_BASE",
    "LLM_BASE_URL",
)


def test_record_step_remembers_the_trace_url(fake_langfuse: str) -> None:
    observe.record_step("draft", input_data={}, output_data={}, model="test-model")

    assert observe.step_trace_url() == fake_langfuse


def test_reset_step_trace_clears_the_url(fake_langfuse: str) -> None:
    observe.record_step("draft", input_data={}, output_data={}, model="test-model")
    assert observe.step_trace_url() == fake_langfuse

    observe.reset_step_trace()

    assert observe.step_trace_url() is None


def test_complete_starts_with_no_step_trace(
    monkeypatch: pytest.MonkeyPatch, fake_langfuse: str
) -> None:
    observe.record_step("old", input_data={}, output_data={}, model="old-model")
    assert observe.step_trace_url() == fake_langfuse
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ProfassistError):
        llm.complete("assignment_text", {"prompt": "Draft it."})

    assert observe.step_trace_url() is None


class _Scalar:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value

    def scalars(self) -> "_Scalar":
        return self

    def all(self) -> list[Any]:
        return []


class _ReviewDB:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, statement: Any) -> _Scalar:
        return _Scalar(0)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1


def test_outline_review_stores_the_step_trace_url(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(id=uuid.uuid4(), course_id=uuid.uuid4(), body={}, instructions="")

    async def fake_get_outline(*args: Any) -> Any:
        return row

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        observe._step_trace.set("http://langfuse.test/traces/review")
        return {"summary": "Two outcomes need work."}

    monkeypatch.setattr(outline_review, "get_outline", fake_get_outline)
    monkeypatch.setattr(llm, "complete", fake_complete)

    result = asyncio.run(
        outline_review.run_review(
            _ReviewDB(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            mode="single",
            reviewer="curriculum",
        )
    )

    assert result["trace_url"] == "http://langfuse.test/traces/review"


def test_run_slide_studio_returns_the_graph_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_invoke(graph: Any, state: dict, *, name: str, metadata: dict | None = None):
        return {"slides": [], "objective": "Compare the two models."}, "http://trace/studio"

    monkeypatch.setattr(slide_studio, "invoke_graph", fake_invoke)

    result = slide_studio.run_slide_studio(
        ["Compare the two models."],
        [{"id": "c1", "text": "A note about the two models.", "filename": "note.txt"}],
    )

    assert result["trace_url"] == "http://trace/studio"
    assert "trace_url" not in result["slides"]
