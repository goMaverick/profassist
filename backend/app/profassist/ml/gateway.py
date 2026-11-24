"""Honest model gateway for ProfAssist.

Only two upstream models exist: course-withdrawal (``student-dropout``) and
passage reuse (``passage-reuse``). There is no pass/fail model. Nothing here
invents a score, a version, or a license the upstream project did not grant.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.profassist.errors import ProfassistError
from app.profassist.ml import dropout

SOURCE = "https://github.com/maxser0v/student-dropout-mlops"
PLAGIARISM_SCHEMA_VERSION = "1.0"
PLAGIARISM_UNAVAILABLE = "The plagiarism worker is not available. Configure it in ML settings."

PLAGIARISM_DATA_NEEDED = (
    "Candidate reports (stable report and document ids plus text) and, optionally, "
    "a corpus of source reports. An external worker computes passage reuse. "
    "ProfAssist stores only the returned flags and never ships an excerpt in an error."
)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _worker_url() -> str:
    return _env("PLAGIARISM_WORKER_URL").rstrip("/")


def dropout_status() -> dict[str, Any]:
    """Adapter status without scoring a student."""
    return dropout.status()


def plagiarism_status(*, probe: bool = False) -> dict[str, Any]:
    """Report whether the external worker is configured.

    No network call happens unless ``probe`` is true. A probe calls ``/health``
    with a three-second timeout. The token is never returned.
    """
    url = _worker_url()
    token_set = bool(_env("PLAGIARISM_WORKER_TOKEN"))
    reachable: bool | None = None
    if probe and url:
        try:
            response = httpx.get(f"{url}/health", timeout=3.0)
            reachable = response.is_success
        except Exception:
            reachable = False
    configured = bool(url) and reachable is not False
    return {
        "model": "passage-reuse",
        "status": "configured" if configured else "not_installed",
        "configured": configured,
        "worker_url": url or None,
        "token_set": token_set,
        "reachable": reachable,
        "probe": probe,
    }


def model_cards() -> list[dict[str, Any]]:
    """Describe the two real models. There is deliberately no pass/fail card."""
    dropout_card = dropout_status()
    plagiarism = plagiarism_status()
    return [
        {
            "name": "student-dropout",
            "kind": "early-warning",
            "status": dropout_card["status"],
            "version": dropout_card["version"],
            "source": SOURCE,
            "license": "upstream has no LICENSE; demo only; redistribution/production needs written permission",
            "data_needed": dropout_card["data_needed"],
            "synthetic": dropout_card["synthetic"],
            "threshold": dropout_card["threshold"],
            "bands": ["review", "routine"],
            "note": (
                "Advisory withdrawal risk after day 35. It never enrols, messages, "
                "or grades a student."
            ),
        },
        {
            "name": "passage-reuse",
            "kind": "integrity",
            "status": plagiarism["status"],
            "version": None,
            "source": SOURCE,
            "license": "not vendored; external worker required",
            "data_needed": PLAGIARISM_DATA_NEEDED,
            "threshold_note": ("0.922696 is PAN-specific and must be re-selected for this corpus."),
            "note": (
                "Passage-reuse reports come from an external worker over JSON. "
                "No model artifacts are in this repository."
            ),
        },
    ]


def _validate_plagiarism_result(result: Any, scope: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE)
    if result.get("schema_version") != PLAGIARISM_SCHEMA_VERSION:
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE)
    if result.get("scope") != scope:
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE)
    flags = result.get("display_flags")
    if not isinstance(flags, list) or not all(isinstance(flag, dict) for flag in flags):
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE)


def score_plagiarism(
    *,
    scope: dict[str, Any],
    reports: list[dict[str, Any]],
    source_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask the external worker to score passage reuse.

    The worker owns the model and the threshold. Any failure becomes a fixed 503
    that names none of the inputs, excerpts, or credentials.
    """
    url = _worker_url()
    if not url:
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE)
    token = _env("PLAGIARISM_WORKER_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body: dict[str, Any] = {
        "scope": scope,
        "reports": reports,
    }
    if source_reports is not None:
        body["source_reports"] = source_reports
    try:
        response = httpx.post(f"{url}/score", json=body, headers=headers, timeout=60.0)
        response.raise_for_status()
        result = response.json()
        _validate_plagiarism_result(result, scope)
    except ProfassistError:
        raise
    except Exception:
        raise ProfassistError(503, PLAGIARISM_UNAVAILABLE) from None
    return result
