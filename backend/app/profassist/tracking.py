"""MLflow client for models that are not trained yet.

The tracking server is optional. When it is down, or has no registered models,
the admin page stays on the empty state. This module never trains anything.
"""

import os
from typing import Any

import httpx


def tracking_uri() -> str:
    return os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000").rstrip("/")


def list_registered_models() -> dict[str, Any]:
    expected = [
        {"name": "grade_calibrator", "status": "not_trained", "version": None},
        {"name": "at_risk_classifier", "status": "not_trained", "version": None},
    ]
    try:
        response = httpx.get(
            f"{tracking_uri()}/api/2.0/mlflow/registered-models/search",
            timeout=3.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {
            "tracking_uri": tracking_uri(),
            "reachable": False,
            "models": expected,
            "message": "No trained model is registered. The calibrator and the early-warning model are not trained yet.",
        }
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
        return {
            "tracking_uri": tracking_uri(),
            "reachable": True,
            "models": expected,
            "message": "MLflow is up and the registry is empty. Nothing has been trained yet.",
        }
    return {
        "tracking_uri": tracking_uri(),
        "reachable": True,
        "models": found,
        "message": "Registered models from MLflow.",
    }
