"""The fixed Assessment 2 brief template.

The eleven report sections and the class-detail labels belong to the template,
not to the model. A draft fills the text around them; it never renames, adds, or
drops a section.
"""

from __future__ import annotations

from typing import Any

# Rendered in this order; the second value is the ``class_details`` key.
CLASS_DETAILS: tuple[tuple[str, str], ...] = (
    ("Institution", "institution"),
    ("Course", "course"),
    ("Lecturer", "lecturer"),
    ("Assessment", "assessment"),
    ("Weight", "weight"),
    ("Report length", "report_length"),
    ("Report due", "report_due"),
    ("Presentation", "presentation"),
    ("Submission", "submission"),
)

# The M2 template. Numbers and titles are fixed; guidelines may be edited.
REPORT_SECTIONS: tuple[dict[str, str], ...] = (
    {
        "number": "1",
        "section": "Executive Summary",
        "guidelines": "The problem, the proposed architecture, and the most important design "
        "decision, readable on its own by a non-technical executive.",
    },
    {
        "number": "2",
        "section": "Problem Definition & Business Context",
        "guidelines": "The industry context, who is affected, and measurable business impact: "
        "the target metric, the current baseline, and the intended improvement.",
    },
    {
        "number": "3",
        "section": "Solution Overview",
        "guidelines": "The end-to-end architecture, shown in a well-labelled architecture "
        "diagram, with each component and data flow explained and the main alternatives you "
        "rejected.",
    },
    {
        "number": "4",
        "section": "Data Strategy",
        "guidelines": "Sources, collection, quality checks, storage, labelling, versioning, "
        "and access controls; how data is kept consistent between training and serving.",
    },
    {
        "number": "5",
        "section": "AI Workflow Design (ML Pipeline)",
        "guidelines": "Pipeline stages from ingestion to model registry, how they are "
        "orchestrated, how experiments are tracked, and how runs are made reproducible.",
    },
    {
        "number": "6",
        "section": "Tool & Technology Stack",
        "guidelines": "The tools chosen, why they were chosen over named alternatives, and "
        "how they integrate; a table is a good fit.",
    },
    {
        "number": "7",
        "section": "Model Deployment & Scalability Strategy",
        "guidelines": "Serving pattern (batch, online, streaming, or edge), CI/CD for models, "
        "rollout and rollback, and how latency and throughput targets are met at scale.",
    },
    {
        "number": "8",
        "section": "Monitoring, Retraining & Maintenance",
        "guidelines": "What is monitored (system, data, model, business), drift detection, "
        "alert thresholds, retraining triggers, and who owns maintenance.",
    },
    {
        "number": "9",
        "section": "Ethical, Regulatory & Risk Considerations",
        "guidelines": "Fairness, explainability, privacy, and the specific legal frameworks "
        "that apply, with the main risks and how they are mitigated.",
    },
    {
        "number": "10",
        "section": "Conclusion & Recommendations",
        "guidelines": "What the design achieves, its main limitations, and a prioritized "
        "path to implementation.",
    },
    {
        "number": "11",
        "section": "References",
        "guidelines": "Every source cited in the text, in one consistent style.",
    },
)


def fixed_report_sections() -> list[dict[str, str]]:
    """A fresh copy, so editing one draft cannot mutate the template."""
    return [dict(item) for item in REPORT_SECTIONS]


def empty_document() -> dict[str, Any]:
    """A draft with every template slot present but no invented text."""
    return {
        "class_details": {key: "" for _label, key in CLASS_DETAILS},
        "overview": [],
        "problem_choices": [],
        "deliverables": [],
        "report_sections": fixed_report_sections(),
    }
