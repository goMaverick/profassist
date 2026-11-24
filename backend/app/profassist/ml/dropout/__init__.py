"""Advisory course-withdrawal adapter.

The feature names come from maxser0v/student-dropout-mlops. See NOTICE.md.
A prediction never enrols, messages, or grades a student.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SOURCE = "https://github.com/maxser0v/student-dropout-mlops"
DEFAULT_THRESHOLD = 0.15
BANDS = ("review", "routine")

# Order matches src/dropout/validation.py FEATURE_COLUMNS in the upstream repo.
FEATURE_COLUMNS = (
    "active_days_14d",
    "active_days_previous_14d",
    "interactions_14d",
    "interactions_previous_14d",
    "resource_views_14d",
    "forum_posts_14d",
    "late_submissions_to_date",
    "assignments_due_to_date",
    "scores_available_count",
    "mean_score_pct_to_date",
    "missed_assignments",
    "activity_change",
    "days_since_last_activity",
    "no_activity_history",
)

DATA_NEEDED = (
    "A day-35 snapshot per enrolment: active days and interactions for the last "
    "14 days and the 14 days before that, resource views, forum posts, late "
    "submissions, assignments due, released marks, and days since the last event. "
    "This demo trains those columns on synthetic Moodle-shaped rows. It is not a "
    "real student model."
)


def _artifact_dir() -> Path:
    return Path(__file__).with_name("artifacts")


def _metrics() -> dict[str, Any]:
    """Read the sidecar written by ``train_synthetic.py``, if it is present."""
    try:
        parsed = json.loads((_artifact_dir() / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bundle() -> dict[str, Any] | None:
    path = _artifact_dir() / "model.joblib"
    if not path.is_file():
        return None
    try:
        import joblib
    except ImportError:
        return None
    try:
        loaded = joblib.load(path)
    except Exception:
        return None
    if not isinstance(loaded, dict) or "model" not in loaded:
        return None
    return loaded


def _threshold(bundle: dict[str, Any] | None) -> float:
    """The bundle owns the decision threshold. Missing values use 0.15."""
    raw = (bundle or {}).get("threshold", DEFAULT_THRESHOLD)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


def _synthetic(bundle: dict[str, Any] | None) -> bool:
    """Whether this bundle was fit on the demo rows.

    The shipped joblib archive predates an explicit flag, so the metrics sidecar
    written by the same training run is the fallback. An unknown bundle is not
    labelled synthetic.
    """
    if bundle is None:
        return False
    if "synthetic" in bundle:
        return bool(bundle["synthetic"])
    return bool(_metrics().get("synthetic", False))


def status() -> dict[str, Any]:
    """Describe the adapter without scoring anyone.

    ``ready`` means a bundle is loadable. It does not mean ProfAssist has the
    activity data needed to score a student.
    """
    bundle = _bundle()
    metrics = _metrics()
    return {
        "model": "student-dropout",
        "kind": "early-warning",
        "status": "ready" if bundle is not None else "not_trained",
        "trained": bundle is not None,
        "version": (bundle or {}).get("version") or metrics.get("version"),
        "source": SOURCE,
        "license": "upstream has no LICENSE; demo only; redistribution/production needs written permission",
        "synthetic": _synthetic(bundle),
        "threshold": _threshold(bundle),
        "bands": list(BANDS),
        "features": list(FEATURE_COLUMNS),
        "data_needed": DATA_NEEDED,
        "automatic_actions": False,
    }


def map_student(
    student: dict[str, Any],
    features: dict[str, Any] | None = None,
    *,
    submissions: int = 0,
    graded: int = 0,
) -> dict[str, Any]:
    """Map what ProfAssist actually stores. Missing LMS logs stay blank, not zero.

    ``features`` is an optional day-35 snapshot supplied by a future LMS import.
    Only the 14 allowlisted columns are copied; extra keys are ignored.
    """
    if features is None:
        mapped: dict[str, Any] = dict.fromkeys(FEATURE_COLUMNS)
        mapped["assignments_due_to_date"] = None
        mapped["scores_available_count"] = graded or None
    else:
        mapped = {column: features.get(column) for column in FEATURE_COLUMNS}
    return {
        "student_key": student.get("external_id") or student.get("id"),
        "features": mapped,
        "available": {
            "roster": True,
            "submissions_seen": submissions,
            "released_grades": graded,
            "activity_log": features is not None,
        },
    }


def _complete(features: dict[str, Any]) -> bool:
    return all(features.get(column) is not None for column in FEATURE_COLUMNS)


def _score_row(bundle: dict[str, Any], values: list[float]) -> tuple[float, list[str]]:
    import pandas as pd

    frame = pd.DataFrame([values], columns=list(FEATURE_COLUMNS))
    from app.profassist.ml.dropout.upstream.training import positive_class_probability

    score = float(positive_class_probability(bundle["model"], frame)[0])
    model = bundle["model"]
    transformed = model[:-1].transform(frame)
    coefs = model.named_steps["classifier"].coef_[0]
    width = min(len(FEATURE_COLUMNS), len(coefs), transformed.shape[1])
    contributions = [
        (FEATURE_COLUMNS[index].replace("_", " "), float(coefs[index] * transformed[0, index]))
        for index in range(width)
    ]
    contributions.sort(key=lambda item: abs(item[1]), reverse=True)
    factors = [f"{name} ({value:+.2f})" for name, value in contributions[:3]]
    return score, factors


def predict(
    students: list[dict[str, Any]],
    *,
    course_code: str = "",
    features_by_student: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score a roster only when a trained bundle and all 14 features are present.

    ``features_by_student`` is the per-course map loaded from the Moodle activity
    table. A per-student ``student["features"]`` still wins, which keeps direct
    callers simple. A blank score is a data gap, not a low risk. Nothing here
    changes enrolment, messages, or marks.
    """
    bundle = _bundle()
    threshold = _threshold(bundle)
    synthetic = _synthetic(bundle)
    rows = []
    for index, student in enumerate(students):
        supplied = student.get("features") if isinstance(student, dict) else None
        if supplied is None and features_by_student is not None:
            key = student.get("external_id") or student.get("id")
            if key is not None:
                supplied = features_by_student.get(str(key))
        mapped = map_student(student, features=supplied)
        features = mapped["features"]
        score: float | None = None
        band: str | None = None
        factors: list[str] = []
        if bundle is not None and _complete(features):
            values = [features[column] for column in FEATURE_COLUMNS]
            try:
                score, factors = _score_row(bundle, values)
            except Exception:
                score, factors = None, []
        if score is None:
            band = None
            factors = []
            note = "Not enough data to score. Connect Moodle activity data first."
        else:
            band = "review" if score >= threshold else "routine"
            note = "Advisory score only. This does not change enrolment or marks."
        rows.append(
            {
                "student_token": f"STUDENT_{index + 1}",
                "display_name": student.get("display_name"),
                "external_id": student.get("external_id"),
                "course_code": course_code,
                "risk": score,
                "score": None if score is None else round(score, 3),
                "band": band,
                "factors": factors,
                "features": features,
                "note": note,
            }
        )
    scored = any(row["score"] is not None for row in rows)
    if scored:
        message = (
            "Advisory scores from the trained model. This does not change a "
            "student's enrolment, messages, or marks."
        )
    elif bundle is None:
        message = (
            "The course-withdrawal model is not trained. Connect Moodle activity data to enable it."
        )
    else:
        message = "A model is present but there is not enough activity data to score."
    return {
        "model": "student-dropout",
        "source": SOURCE,
        "model_type": "logistic regression",
        "status": "trained" if scored else "not_trained",
        "trained": scored,
        "synthetic": synthetic,
        "threshold": threshold,
        "bands": list(BANDS),
        "automatic_actions": False,
        "course_code": course_code,
        "features": list(FEATURE_COLUMNS),
        "data_needed": DATA_NEEDED,
        "message": message,
        "students": rows,
    }
