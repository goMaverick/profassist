"""Train the vendored logistic pipeline on a seeded synthetic day-35 snapshot.

The rows are fictional. Metrics describe that demo set only.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.profassist.ml.dropout.upstream.training import (
    build_pipeline,
    choose_threshold,
    evaluate_probabilities,
    positive_class_probability,
)

from . import FEATURE_COLUMNS

ARTIFACT = Path(__file__).with_name("artifacts")
SEED = 903


def synthesize(rows: int = 480) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    withdrawn = rng.random(rows) < 0.18
    recent = np.where(withdrawn, rng.integers(0, 4, rows), rng.integers(7, 15, rows))
    previous = np.where(withdrawn, rng.integers(6, 13, rows), rng.integers(5, 13, rows))
    interactions = np.where(recent == 0, 0, recent + rng.integers(0, 8, rows))
    previous_interactions = np.where(previous == 0, 0, previous + rng.integers(0, 8, rows))
    forum = np.minimum(interactions, rng.integers(0, 4, rows))
    resource = np.minimum(interactions - forum, rng.integers(0, 6, rows))
    due = np.full(rows, 2)
    submitted = np.where(withdrawn, rng.integers(0, 2, rows), 2)
    late = np.where(
        submitted == 0, 0, np.where(withdrawn, rng.integers(0, 2, rows), rng.integers(0, 2, rows))
    )
    late = np.minimum(late, submitted)
    scores = np.where(submitted == 0, 0, np.where(withdrawn, rng.integers(0, 2, rows), 2))
    scores = np.minimum(scores, submitted)
    mean = np.where(
        scores == 0, 0.0, np.where(withdrawn, rng.uniform(30, 58, rows), rng.uniform(68, 95, rows))
    )
    missed = due - submitted
    change = recent - previous
    days_since = np.where(recent == 0, rng.uniform(14, 35, rows), rng.uniform(0, 3, rows))
    no_history = (recent + previous == 0).astype(float)
    matrix = np.column_stack(
        [
            recent,
            previous,
            interactions,
            previous_interactions,
            resource,
            forum,
            late,
            due,
            scores,
            mean,
            missed,
            change,
            days_since,
            no_history,
        ]
    ).astype(float)
    # Flip a few labels so the fit is not perfect.
    labels = withdrawn.astype(int)
    flip = rng.choice(rows, size=max(1, rows // 12), replace=False)
    labels[flip] = 1 - labels[flip]
    return matrix, labels


def train(rows: int = 480) -> dict:
    matrix, labels = synthesize(rows)
    split = int(rows * 0.8)
    model = build_pipeline(SEED)
    import pandas as pd

    train_frame = pd.DataFrame(matrix[:split], columns=list(FEATURE_COLUMNS))
    model.fit(train_frame, labels[:split])
    holdout = pd.DataFrame(matrix[split:], columns=list(FEATURE_COLUMNS))
    probabilities = positive_class_probability(model, holdout)
    choice = choose_threshold(labels[split:], probabilities, minimum_precision=0.3)
    metrics = evaluate_probabilities(
        labels[split:],
        probabilities,
        choice.threshold or 0.5,
        train_prevalence=float(labels[:split].mean()),
    )
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(
        {"model": model, "threshold": choice.threshold or 0.5, "columns": list(FEATURE_COLUMNS)},
        ARTIFACT / "model.joblib",
    )
    summary = {
        "synthetic": True,
        "rows": rows,
        "threshold": choice.threshold or 0.5,
        "roc_auc": metrics["roc_auc"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "brier_score": metrics["brier_score"],
        "note": "Trained on synthetic data, demo only.",
    }
    (ARTIFACT / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
