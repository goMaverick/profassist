"""MLflow client for models that are not trained yet.

The tracking server is optional. When it is down, or has no registered models,
the admin page stays on the empty state. This module never trains anything and
never invents an MLflow version. It also exposes the gateway model cards so the
admin page can show what is actually shipped next to what the registry holds.
"""

import asyncio
import copy
import os
import time
from typing import Any

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
