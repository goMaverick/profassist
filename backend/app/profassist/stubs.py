"""Interfaces for the two models that are intentionally not trained in this POC."""

from typing import Any


def grade_calibrator(features: dict[str, Any] | None = None) -> dict[str, Any]:
    """The calibrator would adjust a council level. It has no trained weights yet."""
    return {
        "model": "grade_calibrator",
        "status": "not_trained",
        "trained": False,
        "level": None,
        "p_keep": None,
        "features_accepted": sorted((features or {}).keys()),
        "message": (
            "The grade calibrator is not trained yet. It will not change the council's "
            "level. Confident one-click approval stays off until a model is wired in "
            "and the professor's past marks are available."
        ),
    }


def at_risk_snapshot(
    students: list[dict[str, Any]],
    *,
    course_code: str = "",
    features_by_student: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Early-warning page data. The dropout adapter decides whether a model is loaded."""
    from app.profassist.ml.dropout import predict

    return predict(
        students,
        course_code=course_code,
        features_by_student=features_by_student,
    )
