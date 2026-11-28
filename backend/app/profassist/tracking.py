"""MLflow client for the registry and training results.

The tracking server is optional. When it is down, or has no registered models,
the admin page stays on the empty state. This module never trains anything and
never invents an MLflow version. It also exposes the gateway model cards so the
admin page can show what is actually shipped next to what the registry holds.
"""

import asyncio
import copy
import os
import time
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

EXPECTED_MODELS: tuple[dict[str, Any], ...] = (
    {"name": "grade_calibrator", "status": "not_trained", "version": None},
    {"name": "at_risk_classifier", "status": "not_trained", "version": None},
)
REGISTRY_PATH = "/api/2.0/mlflow/registered-models/search"
REGISTRY_TIMEOUT_SECONDS = 5.0
# One page load reads the registry more than once. Cache a reachable answer
# briefly so a slow MLflow does not flip the admin page between states. A
# failure is never cached: a restart must recover on the very next read.
REACHABILITY_TTL_SECONDS = 10.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cached(uri: str) -> dict[str, Any] | None:
    entry = _CACHE.get(uri)
    if entry is None:
        return None
    stored_at, payload = entry
    if time.monotonic() - stored_at >= REACHABILITY_TTL_SECONDS:
        _CACHE.pop(uri, None)
        return None
    return copy.deepcopy(payload)


def _remember(uri: str, payload: dict[str, Any]) -> dict[str, Any]:
    _CACHE[uri] = (time.monotonic(), copy.deepcopy(payload))
    return payload


def _reset_registry_cache() -> None:
    """Tests clear the reachability cache between cases."""
    _CACHE.clear()


def tracking_uri() -> str:
    return os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000").rstrip("/")


async def _training_run(run_id: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=REGISTRY_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{tracking_uri()}/api/2.0/mlflow/runs/get", params={"run_id": run_id}
            )
            response.raise_for_status()
            run = response.json()["run"]
        if not isinstance(run, dict):
            return {}
        return {key: run[key] for key in ("info", "data") if isinstance(run.get(key), dict)}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}


async def training_namespace(run_id: str) -> str:
    data = (await _training_run(run_id)).get("data") or {}
    for tag in data.get("tags") or []:
        if isinstance(tag, dict) and tag.get("key") == "model.namespace":
            name = tag.get("value")
            return name if isinstance(name, str) else ""
    return ""


def _mlflow_run_url(run_id: str, experiment_id: Any) -> str | None:
    if not isinstance(experiment_id, str) or not experiment_id:
        return None
    base = os.getenv("MLFLOW_PUBLIC_URL", "").strip().rstrip("/")
    try:
        url = urlsplit(base)
        if url.scheme not in {"http", "https"} or not url.hostname:
            return None
    except ValueError:
        return None
    if url.username is not None or url.query or url.fragment:
        return None
    return f"{base}/#/experiments/{quote(experiment_id, safe='')}/runs/{quote(run_id, safe='')}"


def prefect_run_url(run_id: str | None) -> str | None:
    base = os.getenv("PREFECT_PUBLIC_URL", "http://localhost:4200").strip().rstrip("/")
    try:
        run = uuid.UUID(run_id or "")
        url = urlsplit(base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.query
            or url.fragment
        ):
            return None
    except ValueError:
        return None
    return f"{base}/runs/flow-run/{run}"


def _metaflow_run_url(data: dict[str, Any]) -> str | None:
    template = os.getenv("METAFLOW_RUN_URL_TEMPLATE", "").strip()
    if "{run_id}" not in template:
        return None
    tags = {
        tag["key"]: tag["value"]
        for tag in data.get("tags") or []
        if isinstance(tag, dict)
        and isinstance(tag.get("key"), str)
        and isinstance(tag.get("value"), str)
    }
    flow, run_id = tags.get("metaflow.flow"), tags.get("metaflow.run_id")
    if not flow or not run_id:
        return None
    href = template.replace("{flow}", quote(flow, safe="")).replace(
        "{run_id}", quote(run_id, safe="")
    )
    try:
        url = urlsplit(href)
    except ValueError:
        return None
    if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None:
        return None
    return href


async def training_metrics(run_id: str, operation: str) -> dict[str, float | str]:
    """Read normalized validation metrics and browser links for a saved run."""
    keys = (
        {"validation_recall": "recall", "validation_minilm_xgboost_precision": "precision"}
        if operation == "plagiarism-train"
        else {"recall": "recall", "precision": "precision"}
    )
    run = await _training_run(run_id)
    data = run.get("data") or {}
    results: dict[str, float | str] = {
        keys[item["key"]]: float(item["value"])
        for item in data.get("metrics") or []
        if isinstance(item, dict)
        and isinstance(item.get("key"), str)
        and item["key"] in keys
        and type(item.get("value")) in (float, int)
        and 0 <= item["value"] <= 1
    }
    info = run.get("info") or {}
    if info.get("run_id") == run_id:
        if url := _mlflow_run_url(run_id, info.get("experiment_id")):
            results["mlflow_url"] = url
        if url := _metaflow_run_url(data):
            results["metaflow_url"] = url
    return results


def _gateway() -> dict[str, Any]:
    from app.profassist.ml.gateway import model_cards

    return {"models": model_cards()}


def _expected() -> list[dict[str, Any]]:
    return [dict(model) for model in EXPECTED_MODELS]


def _empty_payload(message: str, *, reachable: bool) -> dict[str, Any]:
    return {
        "tracking_uri": tracking_uri(),
        "reachable": reachable,
        "models": _expected(),
        "gateway": _gateway(),
        "message": message,
    }


async def _fetch_registry(uri: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=REGISTRY_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{uri}{REGISTRY_PATH}")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return _empty_payload(
            "No trained model is registered. The calibrator and the early-warning "
            "model are not trained yet.",
            reachable=False,
        )
    found = []
    for model in payload.get("registered_models") or []:
        latest = (model.get("latest_versions") or [{}])[0]
        found.append(
            {
                "name": model.get("name"),
                "status": latest.get("current_stage") or "registered",
                "version": latest.get("version"),
            }
        )
    if not found:
        return _empty_payload(
            "MLflow is up and the registry is empty. Nothing has been trained yet.",
            reachable=True,
        )
    return {
        "tracking_uri": tracking_uri(),
        "reachable": True,
        "models": found,
        "gateway": _gateway(),
        "message": "Registered models from MLflow.",
    }


async def list_registered_models_async() -> dict[str, Any]:
    """Read the MLflow registry without blocking the event loop.

    Only a success is cached for ``REACHABILITY_TTL_SECONDS``: it keeps one page
    load from flapping between states. A failure is not cached, so a read that
    raced MLflow's startup is retried instead of served stale for ten seconds.
    """
    uri = tracking_uri()
    cached = _cached(uri)
    if cached is not None:
        return cached
    payload = await _fetch_registry(uri)
    if not payload.get("reachable"):
        _CACHE.pop(uri, None)
        return payload
    return _remember(uri, payload)


def list_registered_models() -> dict[str, Any]:
    """Synchronous compatibility entry point.

    Tests and any offline script import this name. Callers inside an async
    context should ``await list_registered_models_async()`` instead; running a
    nested event loop here would raise, so the sync path reports the empty state
    rather than stalling the loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(list_registered_models_async())
    return _empty_payload(
        "The model registry is queried asynchronously. The caller must await "
        "list_registered_models_async().",
        reachable=False,
    )
