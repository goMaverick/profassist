"Admin ML control room: route registration, admin auth, cards, and probe redaction."

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.api.routes.v1 import ml_admin
from app.core.config import settings
from app.main import app
from app.profassist.ml import gateway


def _user(admin: bool) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_app_admin=admin)


def _override(admin: bool) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.profassist.deps import get_profassist_org

    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: _user(admin)
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=uuid.uuid4())


class _Response:
    def __init__(self, payload: Any = None) -> None:
        self.payload = payload or {}

    def json(self) -> Any:
        return self.payload

    @property
    def is_success(self) -> bool:
        return True


@pytest.mark.anyio
async def test_ml_admin_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    prefix = "/api/v1/profassist/admin/ml"
    assert f"{prefix}/models" in paths
    assert f"{prefix}/plagiarism/probe" in paths
    assert f"{prefix}/plagiarism/contract" in paths
    assert f"{prefix}/jobs/{{job_id}}/metrics" in paths


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin/ml/models"),
        ("post", "/admin/ml/plagiarism/probe"),
        ("get", "/admin/ml/plagiarism/contract"),
        ("get", "/admin/ml/jobs/00000000-0000-0000-0000-000000000001/metrics"),
    ],
)
async def test_non_admin_is_forbidden(client, method: str, path: str) -> None:
    _override(False)

    response = await getattr(client, method)(f"{settings.API_V1_STR}/profassist{path}")

    assert response.status_code == 403, response.text


@pytest.mark.anyio
async def test_models_payload_has_two_cards_and_no_pass_fail(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override(True)
    monkeypatch.delenv("PLAGIARISM_WORKER_URL", raising=False)
    monkeypatch.delenv("PLAGIARISM_WORKER_TOKEN", raising=False)

    async def fake_registry() -> dict[str, Any]:
        return {"reachable": True, "tracking_uri": "http://mlflow:5000"}

    monkeypatch.setattr(ml_admin, "list_registered_models_async", fake_registry)

    response = await client.get(f"{settings.API_V1_STR}/profassist/admin/ml/models")

    assert response.status_code == 200, response.text
    body = response.json()
    names = [card["name"] for card in body["models"]]
    assert names == ["student-dropout", "passage-reuse"]
    assert all(name not in {"pass/fail", "pass-fail"} for name in names)

    dropout = body["models"][0]
    reuse = body["models"][1]
    assert {"name", "kind", "status", "source", "license", "data_needed", "note"} <= dropout.keys()
    assert dropout["kind"] == "early-warning"
    assert dropout["status"] in {"ready", "not_trained"}
    assert dropout["synthetic"] is True
    assert len(dropout["features"]) == 14
    assert dropout["bands"] == ["review", "routine"]

    assert reuse["kind"] == "integrity"
    assert reuse["status"] == "not_installed"
    assert "0.922696" in reuse["threshold_note"]

    assert body["settings"] == {
        "worker_url_set": False,
        "worker_token_set": False,
        "worker_host": None,
        "env_only": True,
    }
    assert body["mlflow"] == {"reachable": True, "tracking_uri": "http://mlflow:5000"}


@pytest.mark.anyio
async def test_training_metrics_uses_the_saved_run_and_current_organization(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_db_session
    from app.profassist import tracking
    from app.profassist.deps import get_profassist_org

    _override(True)
    org_id, job_id = uuid.uuid4(), uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        organization_id=org_id,
        operation="plagiarism-train",
        status="completed",
        result={"training_run_id": "registered-training-run"},
    )
    seen = []
    run_info = {"run_id": "registered-training-run", "experiment_id": "42"}

    async def get(_model, row_id):
        assert row_id == job_id
        return job

    async def read_run(run_id):
        seen.append(run_id)
        return {
            "info": run_info,
            "data": {
                "metrics": [{"key": "validation_recall", "value": 0.75}],
                "tags": [
                    {"key": "metaflow.flow", "value": "PlagiarismTrainingFlow"},
                    {"key": "metaflow.run_id", "value": "123456"},
                ],
            },
        }

    app.dependency_overrides[get_db_session] = lambda: SimpleNamespace(get=get)
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)
    monkeypatch.setattr(tracking, "_training_run", read_run)
    monkeypatch.setenv("MLFLOW_PUBLIC_URL", "https://models.example/mlflow/")
    monkeypatch.setenv("METAFLOW_RUN_URL_TEMPLATE", "https://flows.example/{flow}/{run_id}")
    url = f"{settings.API_V1_STR}/profassist/admin/ml/jobs/{job_id}/metrics"

    response = await client.get(url, params={"run_id": "different-run"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "recall": 0.75,
        "mlflow_url": "https://models.example/mlflow/#/experiments/42/runs/registered-training-run",
        "metaflow_url": "https://flows.example/PlagiarismTrainingFlow/123456",
    }

    run_info["run_id"] = "different-run"
    response = await client.get(url)
    assert response.json() == {"recall": 0.75}
    run_info["run_id"] = "registered-training-run"

    monkeypatch.delenv("MLFLOW_PUBLIC_URL")
    monkeypatch.delenv("METAFLOW_RUN_URL_TEMPLATE")
    response = await client.get(url)
    assert response.json() == {"recall": 0.75}

    job.organization_id = uuid.uuid4()
    response = await client.get(url)
    assert response.status_code == 404
    assert seen == ["registered-training-run"] * 3


@pytest.mark.anyio
async def test_probe_success_uses_three_seconds_and_hides_the_token(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override(True)
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")
    seen: dict[str, Any] = {}

    def fake_get(url: str, timeout: float) -> _Response:
        seen["url"] = url
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(gateway.httpx, "get", fake_get)

    response = await client.post(f"{settings.API_V1_STR}/profassist/admin/ml/plagiarism/probe")

    assert response.status_code == 200, response.text
    body = response.json()
    assert seen == {"url": "https://worker.example/health", "timeout": 3.0}
    assert body["configured"] is True
    assert body["reachable"] is True
    assert body["worker_url_set"] is True
    assert body["worker_host"] == "worker.example"
    assert body["token_set"] is True
    assert "error" not in body
    assert "worker_url" not in body
    assert "secret-token" not in response.text
    assert "worker.example/health" not in response.text


@pytest.mark.anyio
async def test_probe_failure_is_redacted(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _override(True)
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://user:pass@worker.example/private")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")

    def boom(url: str, timeout: float) -> _Response:
        raise httpx.ConnectError("secret-token CANDIDATE EXCERPT")

    monkeypatch.setattr(gateway.httpx, "get", boom)

    response = await client.post(f"{settings.API_V1_STR}/profassist/admin/ml/plagiarism/probe")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is False
    assert body["reachable"] is False
    assert body["worker_host"] is None
    assert body["error"] == ml_admin._PROBE_FAILED
    assert "secret-token" not in response.text
    assert "CANDIDATE" not in response.text
    assert "user:pass" not in response.text


@pytest.mark.anyio
async def test_probe_without_a_worker_is_unconfigured(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override(True)
    monkeypatch.delenv("PLAGIARISM_WORKER_URL", raising=False)
    monkeypatch.delenv("PLAGIARISM_WORKER_TOKEN", raising=False)

    response = await client.post(f"{settings.API_V1_STR}/profassist/admin/ml/plagiarism/probe")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is False
    assert body["reachable"] is None
    assert body["worker_url_set"] is False
    assert body["worker_host"] is None
    assert body["error"] == ml_admin._PROBE_UNCONFIGURED


@pytest.mark.anyio
async def test_contract_is_static_and_secret_free(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _override(True)
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")

    response = await client.get(f"{settings.API_V1_STR}/profassist/admin/ml/plagiarism/contract")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["request"]["scope"] == {"assignment_id": "a1"}
    assert body["response"]["schema_version"] == "1.0"
    assert "secret-token" not in response.text
    assert "worker.example" not in response.text


@pytest.mark.anyio
async def test_models_never_returns_worker_credentials(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override(True)
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "https://user:pass@worker.example/private")
    monkeypatch.setenv("PLAGIARISM_WORKER_TOKEN", "secret-token")

    async def fake_registry() -> dict[str, Any]:
        return {"reachable": False, "tracking_uri": "http://mlflow:5000"}

    monkeypatch.setattr(ml_admin, "list_registered_models_async", fake_registry)

    response = await client.get(f"{settings.API_V1_STR}/profassist/admin/ml/models")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["models"][1]["status"] == "configured"
    assert body["mlflow"]["reachable"] is False
    assert body["settings"]["worker_url_set"] is True
    assert body["settings"]["worker_token_set"] is True
    assert body["settings"]["worker_host"] is None
    assert "secret-token" not in response.text
    assert "user:pass" not in response.text
