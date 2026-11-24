"""Unit tests for the honest ML gateway. HTTP is mocked; no network."""

from typing import Any

import httpx
import pytest

from app.profassist.errors import ProfassistError
from app.profassist.ml import dropout, gateway


class _Response:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://worker.example/score")
            raise httpx.HTTPStatusError(
                "worker error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> Any:
        return self.payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


class _BadJsonResponse(_Response):
    def json(self) -> Any:
        raise ValueError("CANDIDATE EXCERPT and secret-token")


def _all_features(value: float = 1.0) -> dict[str, float]:
    return dict.fromkeys(dropout.FEATURE_COLUMNS, value)


def test_model_cards_name_two_real_models_and_no_pass_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAGIARISM_WORKER_URL", raising=False)
    monkeypatch.delenv("PLAGIARISM_WORKER_TOKEN", raising=False)

    cards = gateway.model_cards()

    assert [card["name"] for card in cards] == ["student-dropout", "passage-reuse"]
    dropout_card = cards[0]
    assert dropout_card["kind"] == "early-warning"
    assert dropout_card["status"] in {"ready", "not_trained"}
    assert dropout_card["source"] == "https://github.com/maxser0v/student-dropout-mlops"
    assert (
        dropout_card["license"]
        == "upstream has no LICENSE; demo only; redistribution/production needs written permission"
    )
    assert dropout_card["data_needed"]
    assert dropout_card["synthetic"] is True
    assert dropout_card["threshold"] == pytest.approx(0.1)
    assert dropout_card["bands"] == ["review", "routine"]

    integrity = cards[1]
    assert integrity["kind"] == "integrity"
    assert integrity["status"] == "not_installed"
    assert integrity["license"] == "not vendored; external worker required"
    assert "0.922696" in integrity["threshold_note"]
    assert integrity["data_needed"]

    assert all(card["name"] != "pass/fail" for card in cards)
    assert all(card["kind"] != "pass-fail" for card in cards)


def test_dropout_status_reflects_the_shipped_synthetic_bundle() -> None:
    info = dropout.status()

    assert info["status"] == "ready"
    assert info["synthetic"] is True
    assert info["threshold"] == pytest.approx(0.1)
    assert info["bands"] == ["review", "routine"]
    assert (
        info["license"]
        == "upstream has no LICENSE; demo only; redistribution/production needs written permission"
    )
    assert len(info["features"]) == 14


def test_predict_uses_the_bundle_threshold_for_bands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bundle: dict[str, Any] = {"model": object(), "threshold": 0.4, "synthetic": True}
    monkeypatch.setattr(dropout, "_bundle", lambda: fake_bundle)
    monkeypatch.setattr(dropout, "_score_row", lambda bundle, values: (0.39, ["factor"]))
    below = dropout.predict([{"external_id": "s1", "features": _all_features()}])
    assert below["threshold"] == pytest.approx(0.4)
    assert below["students"][0]["risk"] == pytest.approx(0.39)
    assert below["students"][0]["band"] == "routine"

    monkeypatch.setattr(dropout, "_score_row", lambda bundle, values: (0.4, []))
    at = dropout.predict([{"external_id": "s1", "features": _all_features()}])
    assert at["students"][0]["band"] == "review"


def test_default_threshold_is_used_when_the_bundle_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dropout, "_bundle", lambda: None)

    payload = dropout.predict([{"external_id": "s1", "features": _all_features()}])

    assert payload["threshold"] == pytest.approx(0.15)
    assert payload["status"] == "not_trained"
    assert payload["synthetic"] is False
    assert payload["students"][0]["score"] is None
    assert payload["students"][0]["band"] is None


def test_predict_does_not_score_without_features() -> None:
    payload = dropout.predict([{"display_name": "Sara", "external_id": "s1"}])

    assert payload["trained"] is False
    assert payload["status"] == "not_trained"
    assert payload["students"][0]["score"] is None
    assert payload["students"][0]["band"] is None
    assert payload["students"][0]["factors"] == []
    assert payload["students"][0]["note"].startswith("Not enough data")


def test_predict_requires_every_feature_even_when_some_are_supplied() -> None:
    partial = dict.fromkeys(dropout.FEATURE_COLUMNS[:-1], 1.0)

    payload = dropout.predict([{"external_id": "s1", "features": partial}])

    assert payload["students"][0]["score"] is None
    assert payload["students"][0]["band"] is None


def test_predict_scores_a_complete_provided_snapshot() -> None:
    features = {
        "active_days_14d": 0,
        "active_days_previous_14d": 0,
        "interactions_14d": 0,
        "interactions_previous_14d": 0,
        "resource_views_14d": 0,
        "forum_posts_14d": 0,
        "late_submissions_to_date": 0,
        "assignments_due_to_date": 2,
        "scores_available_count": 0,
        "mean_score_pct_to_date": 0.0,
        "missed_assignments": 2,
        "activity_change": 0,
        "days_since_last_activity": 30,
        "no_activity_history": 1,
    }

    payload = dropout.predict([{"display_name": "Sara", "external_id": "s1", "features": features}])
    row = payload["students"][0]

    assert payload["status"] == "trained"
    assert payload["trained"] is True
    assert payload["synthetic"] is True
    assert row["score"] is not None
    assert row["risk"] is not None
    assert row["band"] == ("review" if row["risk"] >= payload["threshold"] else "routine")
    assert row["factors"]
    assert set(row["features"]) == set(dropout.FEATURE_COLUMNS)


def test_map_student_accepts_a_complete_snapshot() -> None:
    features = dict.fromkeys(dropout.FEATURE_COLUMNS, 2)

    mapped = dropout.map_student({"external_id": "s1"}, features=features)

    assert mapped["student_key"] == "s1"
    assert mapped["features"] == features
    assert mapped["available"]["activity_log"] is True


def test_plagiarism_is_not_installed_without_a_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAGIARISM_WORKER_URL", raising=False)
    monkeypatch.delenv("PLAGIARISM_WORKER_TOKEN", raising=False)

    status = gateway.plagiarism_status()

    assert status["status"] == "not_installed"
    assert status["configured"] is False
    assert status["worker_url"] is None
    assert status["token_set"] is False
    assert status["reachable"] is None
    with pytest.raises(ProfassistError) as caught:
        gateway.score_plagiarism(scope={"assignment_id": "a1"}, reports=[])
    assert caught.value.status == 503
    assert caught.value.detail == gateway.PLAGIARISM_UNAVAILABLE


def test_configured_worker_receives_body_and_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example/")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")
    seen: dict[str, Any] = {}
    result_payload = {
        "schema_version": "1.0",
        "scope": {"assignment_id": "a1"},
        "display_flags": [{"report_id": "r1", "severity": "review"}],
        "run_id": "worker-run-1",
    }

    def fake_post(url: str, **kwargs: Any) -> _Response:
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _Response(result_payload)

    monkeypatch.setattr(gateway.httpx, "post", fake_post)
    scope = {"assignment_id": "a1"}
    reports = [{"report_id": "r1", "text": "the candidate text"}]
    source_reports = [{"report_id": "s1", "text": "a source"}]

    result = gateway.score_plagiarism(
        scope=scope,
        reports=reports,
        source_reports=source_reports,
    )

    assert result == result_payload
    assert seen["url"] == "https://worker.example/score"
    assert seen["kwargs"]["timeout"] == 60.0
    assert seen["kwargs"]["headers"]["Authorization"] == "Bearer secret-token"
    assert seen["kwargs"]["json"] == {
        "scope": scope,
        "reports": reports,
        "source_reports": source_reports,
    }
    status = gateway.plagiarism_status()
    assert status["status"] == "configured"
    assert status["token_set"] is True
    assert "secret-token" not in str(status)


def test_score_omits_source_reports_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example")
    monkeypatch.delenv("PLAGIARISM_WORKER_TOKEN", raising=False)
    seen: dict[str, Any] = {}
    scope = {"assignment_id": "a1"}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        seen.update(kwargs)
        return _Response({"schema_version": "1.0", "scope": scope, "display_flags": []})

    monkeypatch.setattr(gateway.httpx, "post", fake_post)

    gateway.score_plagiarism(scope=scope, reports=[])

    assert "source_reports" not in seen["json"]
    assert "Authorization" not in seen["headers"]


@pytest.mark.parametrize(
    "failure",
    ["http_500", "network", "bad_json", "wrong_schema", "wrong_scope", "bad_flags"],
)
def test_worker_failure_is_a_fixed_503_without_leaks(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")
    scope = {"assignment_id": "a1"}
    good: dict[str, Any] = {
        "schema_version": "1.0",
        "scope": scope,
        "display_flags": [],
    }

    def fake_post(url: str, **kwargs: Any) -> _Response:
        if failure == "network":
            raise httpx.ConnectError("connection refused for secret-token")
        if failure == "http_500":
            return _Response({"detail": "CANDIDATE EXCERPT"}, status_code=500)
        if failure == "bad_json":
            return _BadJsonResponse(None)
        if failure == "wrong_schema":
            return _Response({**good, "schema_version": "9.9"})
        if failure == "wrong_scope":
            return _Response({**good, "scope": {"assignment_id": "other"}})
        return _Response({**good, "display_flags": "CANDIDATE EXCERPT"})

    monkeypatch.setattr(gateway.httpx, "post", fake_post)

    with pytest.raises(ProfassistError) as caught:
        gateway.score_plagiarism(
            scope=scope,
            reports=[{"report_id": "r1", "text": "CANDIDATE EXCERPT"}],
        )

    assert caught.value.status == 503
    assert caught.value.detail == gateway.PLAGIARISM_UNAVAILABLE
    assert "CANDIDATE" not in caught.value.detail
    assert "secret-token" not in caught.value.detail


def test_probe_calls_health_with_a_three_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example/")
    seen: dict[str, Any] = {}

    def fake_get(url: str, timeout: float) -> _Response:
        seen["url"] = url
        seen["timeout"] = timeout
        return _Response({}, status_code=200)

    monkeypatch.setattr(gateway.httpx, "get", fake_get)

    status = gateway.plagiarism_status(probe=True)

    assert seen == {"url": "https://worker.example/health", "timeout": 3.0}
    assert status["reachable"] is True
    assert status["status"] == "configured"


def test_probe_failure_downgrades_to_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example")
    monkeypatch.setattr(
        gateway.httpx,
        "get",
        lambda url, timeout: _Response({}, status_code=503),
    )

    status = gateway.plagiarism_status(probe=True)

    assert status["reachable"] is False
    assert status["status"] == "not_installed"


@pytest.mark.anyio
async def test_registry_async_reads_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.tracking import list_registered_models_async

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")

    payload = await list_registered_models_async()

    assert payload["reachable"] is False
    assert {"tracking_uri", "reachable", "models", "gateway", "message"} <= payload.keys()
    assert payload["models"][0]["status"] == "not_trained"


@pytest.mark.anyio
async def test_registry_reachability_is_cached_between_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One page load reads the registry twice; a slow MLflow must not flap."""
    from app.profassist import tracking

    tracking._reset_registry_cache()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.cache-test:5000")
    calls: list[str] = []

    async def fake_fetch(uri: str) -> dict:
        calls.append(uri)
        return {
            "tracking_uri": uri,
            "reachable": True,
            "models": [],
            "gateway": {"models": []},
            "message": "cached",
        }

    monkeypatch.setattr(tracking, "_fetch_registry", fake_fetch)

    first = await tracking.list_registered_models_async()
    second = await tracking.list_registered_models_async()

    assert first["reachable"] is True
    assert second == first
    assert calls == ["http://mlflow.cache-test:5000"]
    assert tracking.REGISTRY_TIMEOUT_SECONDS >= 5.0
    tracking._reset_registry_cache()


@pytest.mark.anyio
async def test_registry_failure_is_not_cached_so_the_next_read_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MLflow may still be starting: a failed read must not stick for 10s."""
    from app.profassist import tracking

    tracking._reset_registry_cache()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.retry-test:5000")
    calls: list[str] = []
    replies = [
        {
            "tracking_uri": "http://mlflow.retry-test:5000",
            "reachable": False,
            "models": [],
            "gateway": {"models": []},
            "message": "still starting",
        },
        {
            "tracking_uri": "http://mlflow.retry-test:5000",
            "reachable": True,
            "models": [],
            "gateway": {"models": []},
            "message": "up now",
        },
    ]

    async def fake_fetch(uri: str) -> dict:
        calls.append(uri)
        return replies.pop(0)

    monkeypatch.setattr(tracking, "_fetch_registry", fake_fetch)

    first = await tracking.list_registered_models_async()
    second = await tracking.list_registered_models_async()

    assert first["reachable"] is False
    assert second["reachable"] is True
    assert len(calls) == 2

    # A success is still cached for the rest of the page load.
    third = await tracking.list_registered_models_async()
    assert third == second
    assert len(calls) == 2
    tracking._reset_registry_cache()


def test_registry_payload_keeps_shape_and_adds_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist.tracking import list_registered_models

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")

    payload = list_registered_models()

    assert payload["reachable"] is False
    assert {"tracking_uri", "reachable", "models", "gateway", "message"} <= payload.keys()
    assert all(model["version"] is None for model in payload["models"])
    names = {card["name"] for card in payload["gateway"]["models"]}
    assert names == {"student-dropout", "passage-reuse"}
