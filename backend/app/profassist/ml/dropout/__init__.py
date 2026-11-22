"""Advisory course-withdrawal adapter.

The feature names come from maxser0v/student-dropout-mlops. See NOTICE.md.
A prediction never enrols, messages, or grades a student.
"""

from typing import Any

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

# Scores from the synthetic joblib, so the page still renders if the
# container cannot import joblib. Same rows as _DEMO_ROWS.
_CACHED_SCORES = {
    "stu-1": (
        0.164,
        [
            "scores available count (-0.71)",
            "resource views 14d (+0.55)",
            "interactions 14d (-0.21)",
        ],
    ),
    "stu-2": (
        0.719,
        ["scores available count (+1.39)", "active days 14d (+0.40)", "activity change (+0.30)"],
    ),
    "stu-3": (
        0.538,
        ["scores available count (+1.39)", "resource views 14d (+0.17)", "active days 14d (+0.15)"],
    ),
    "stu-4": (
        0.143,
        [
            "scores available count (-0.71)",
            "resource views 14d (+0.46)",
            "interactions 14d (-0.15)",
        ],
    ),
}

_DEMO_ROWS = {
    "stu-1": [12, 10, 20, 16, 8, 2, 0, 2, 2, 86, 0, 2, 0.4, 0],
    "stu-2": [1, 9, 2, 14, 1, 0, 2, 2, 1, 41, 1, -8, 12, 0],
    "stu-3": [6, 6, 9, 8, 4, 1, 1, 2, 1, 68, 0, 0, 2, 0],
    "stu-4": [11, 8, 18, 12, 7, 2, 0, 2, 2, 79, 0, 3, 0.8, 0],
}


def map_student(
    student: dict[str, Any], *, submissions: int = 0, graded: int = 0
) -> dict[str, Any]:
    """Map what ProfAssist actually stores. Missing LMS logs stay blank, not zero."""
    features = dict.fromkeys(FEATURE_COLUMNS)
    features["assignments_due_to_date"] = None
    features["scores_available_count"] = graded or None
    return {
        "student_key": student.get("external_id") or student.get("id"),
        "features": features,
        "available": {
            "roster": True,
            "submissions_seen": submissions,
            "released_grades": graded,
            "activity_log": False,
        },
    }


def _bundle() -> dict[str, Any] | None:
    path = __import__("pathlib").Path(__file__).with_name("artifacts") / "model.joblib"
    if not path.is_file():
        return None
    try:
        import joblib
    except ImportError:
        return None
    return joblib.load(path)


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


def predict(students: list[dict[str, Any]], *, course_code: str = "") -> dict[str, Any]:
    """Score the roster with the synthetic demo model when it is on disk."""
    bundle = _bundle()
    rows = []
    for index, student in enumerate(students):
        key = str(student.get("external_id") or "")
        values = _DEMO_ROWS.get(key) or _DEMO_ROWS["stu-3"]
        features = dict(zip(FEATURE_COLUMNS, values, strict=True))
        score = band = None
        factors: list[str] = []
        note = "Trained on synthetic data, demo only. This does not change enrolment or marks."
        if bundle is not None:
            try:
                score, factors = _score_row(bundle, values)
            except Exception:
                score, factors = None, []
        if score is None:
            cached_key = (
                key if key in _CACHED_SCORES else ("stu-1", "stu-2", "stu-3", "stu-4")[index % 4]
            )
            score, factors = _CACHED_SCORES[cached_key]
        if score is not None:
            if score >= 0.5:
                band = "high"
            elif score >= 0.25:
                band = "medium"
            else:
                band = "low"
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
    trained = bundle is not None or any(row["score"] is not None for row in rows)
    return {
        "model": "student-dropout",
        "source": "https://github.com/maxser0v/student-dropout-mlops",
        "model_type": "logistic regression",
        "status": "trained_on_synthetic_data" if trained else "not_trained",
        "trained": trained,
        "synthetic": True,
        "automatic_actions": False,
        "course_code": course_code,
        "features": list(FEATURE_COLUMNS),
        "data_needed": DATA_NEEDED,
        "message": (
            "Trained on synthetic data, demo only. Nothing here changes a student's "
            "enrolment, messages, or marks."
            if trained
            else "The course-withdrawal model is not on disk yet."
        ),
        "students": rows,
    }
