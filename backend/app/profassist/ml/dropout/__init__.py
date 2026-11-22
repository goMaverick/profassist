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
    "A day-35 LMS snapshot per enrolment: active days and interactions for the "
    "last 14 days and the 14 days before that, resource views, forum posts, "
    "assignments due and submitted, late submissions, released marks, and the "
    "timestamp of the last learner event. The public repository keeps those "
    "rows behind a DVC pointer (data.dvc) and does not commit a model file, so "
    "this checkout cannot train or load student-dropout version 1."
)


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


def predict(students: list[dict[str, Any]], *, course_code: str = "") -> dict[str, Any]:
    """Return an advisory payload. Untrained models do not invent a score."""
    rows = []
    for index, student in enumerate(students):
        mapped = map_student(student)
        rows.append(
            {
                "student_token": f"STUDENT_{index + 1}",
                "display_name": student.get("display_name"),
                "external_id": student.get("external_id"),
                "course_code": course_code,
                "risk": None,
                "score": None,
                "band": None,
                "factors": [],
                "features": mapped["features"],
                "note": "No prediction. The course-withdrawal model is not trained in this checkout.",
            }
        )
    return {
        "model": "student-dropout",
        "source": "https://github.com/maxser0v/student-dropout-mlops",
        "model_type": "logistic regression (upstream); not loaded here",
        "status": "not_trained",
        "trained": False,
        "automatic_actions": False,
        "course_code": course_code,
        "features": list(FEATURE_COLUMNS),
        "data_needed": DATA_NEEDED,
        "message": (
            "The course-withdrawal model is not trained yet. Nothing here changes a "
            "student's enrolment, messages, or marks. It is a note for the professor only."
        ),
        "students": rows,
    }
