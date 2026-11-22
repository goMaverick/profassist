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


def at_risk_snapshot(students: list[dict[str, Any]]) -> dict[str, Any]:
    """Early-warning page data. Scores are placeholders, not predictions."""
    rows = []
    for index, student in enumerate(students):
        rows.append(
            {
                "student_token": f"STUDENT_{index + 1}",
                "display_name": student.get("display_name"),
                "external_id": student.get("external_id"),
                "risk": None,
                "score": None,
                "factors": [],
                "note": "No prediction. The early-warning model is not trained yet.",
            }
        )
    return {
        "model": "at_risk_classifier",
        "status": "not_trained",
        "trained": False,
        "message": (
            "The at-risk early-warning model is not trained yet. The roster below is "
            "real demo data from the fake Moodle connector. The risk column is empty "
            "on purpose."
        ),
        "students": rows,
    }
