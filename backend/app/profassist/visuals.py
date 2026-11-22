"""Chart series for the professor pages.

The shapes are a seeded synthetic Moodle term so the dashboard, outline,
assignments, grading, risk, and similarity views have something to draw.
Live counts from the database can override the headline numbers.
"""

from __future__ import annotations

import random
from typing import Any

NOTE = "Synthetic Moodle data, demo only."


def page_visuals(page: str, *, live: dict[str, Any] | None = None) -> dict[str, Any]:
    rng = random.Random(903)
    weeks = [f"Week {index}" for index in range(1, 12)]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    heatmap = []
    for week in weeks:
        for day_index, day in enumerate(days):
            base = 8 if day_index < 5 else 2
            heatmap.append({"week": week, "day": day, "value": base + rng.randint(0, 6)})
    weights = [
        {"name": "A1 Report", "weight": 25},
        {"name": "A2 Project", "weight": 25},
        {"name": "A3 Build", "weight": 40},
        {"name": "A4 Reflection", "weight": 10},
    ]
    workload = [{"week": week, "hours": 4 + rng.randint(0, 6)} for week in weeks]
    bloom = [
        {"level": "Remember", "count": 1},
        {"level": "Understand", "count": 2},
        {"level": "Apply", "count": 4},
        {"level": "Analyse", "count": 3},
        {"level": "Evaluate", "count": 3},
        {"level": "Create", "count": 2},
    ]
    on_time = [
        {"week": week, "on_time": 12 + rng.randint(0, 8), "late": rng.randint(0, 5)}
        for week in weeks[:6]
    ]
    grades = [
        {"bin": label, "count": count}
        for label, count in zip(
            ["0-49", "50-59", "60-69", "70-79", "80-89", "90-100"],
            [2, 4, 9, 14, 11, 6],
            strict=True,
        )
    ]
    agreement = [
        {"criterion": "Evidence", "spread": 1},
        {"criterion": "Method", "spread": 0},
        {"criterion": "Limitation", "spread": 2},
        {"criterion": "Style", "spread": 1},
    ]
    rounds = [
        {
            "round": index,
            "evidence": 3,
            "strict": max(1, 4 - index),
            "supportive": min(4, 2 + index),
        }
        for index in range(1, 5)
    ]
    risk_bins = [
        {"band": "Low", "count": 62},
        {"band": "Medium", "count": 14},
        {"band": "High", "count": 8},
    ]
    factors = [
        {"name": "Active days", "value": 0.42},
        {"name": "Late submissions", "value": 0.31},
        {"name": "Early marks", "value": 0.22},
        {"name": "Forum posts", "value": 0.11},
    ]
    trend = [{"week": week, "high": max(1, 10 - index)} for index, week in enumerate(weeks)]
    pairs = ["A", "B", "C", "D", "E"]
    matrix = []
    for left in pairs:
        for right in pairs:
            score = 1 if left == right else round(rng.random() * 0.7, 2)
            matrix.append({"left": left, "right": right, "score": score})
    kpis = {
        "courses": 6,
        "students": 84,
        "due": 3,
        "awaiting": 2,
        "at_risk": 8,
        "flags": 1,
    }
    if live:
        kpis["courses"] = live.get("courses", kpis["courses"])
        kpis["students"] = live.get("students", kpis["students"])
        kpis["awaiting"] = live.get("drafts", kpis["awaiting"])
        kpis["flags"] = live.get("open_flags", kpis["flags"])
    deadlines = [
        {"name": "A1 Group report", "when": "Week 4"},
        {"name": "A2 Design project", "when": "Week 7"},
        {"name": "A3 Build", "when": "Week 11"},
    ]
    verdicts = [
        {"group": "Group A", "level": "Proficient"},
        {"group": "Group B", "level": "Developing"},
        {"group": "Group C", "level": "Proficient"},
    ]
    agents = [
        {"name": "Curriculum", "calls": 42, "latency": 1.8, "cost": 0.42},
        {"name": "Judge", "calls": 18, "latency": 2.4, "cost": 0.31},
        {"name": "Slide studio", "calls": 11, "latency": 3.1, "cost": 0.22},
        {"name": "Chat", "calls": 27, "latency": 1.2, "cost": 0.15},
    ]
    return {
        "page": page,
        "synthetic": True,
        "note": NOTE,
        "kpis": kpis,
        "heatmap": heatmap,
        "days": days,
        "weeks": weeks,
        "weights": weights,
        "workload": workload,
        "bloom": bloom,
        "on_time": on_time,
        "grades": grades,
        "agreement": agreement,
        "rounds": rounds,
        "risk_bins": risk_bins,
        "factors": factors,
        "trend": trend,
        "matrix": matrix,
        "pairs": pairs,
        "deadlines": deadlines,
        "verdicts": verdicts,
        "agents": agents,
        "coverage": [
            {"clo": "LO1", "plo": "PLO1", "value": 1},
            {"clo": "LO1", "plo": "PLO2", "value": 1},
            {"clo": "LO2", "plo": "PLO2", "value": 1},
            {"clo": "LO3", "plo": "PLO5", "value": 1},
            {"clo": "LO5", "plo": "PLO1", "value": 1},
            {"clo": "LO6", "plo": "PLO6", "value": 1},
        ],
    }
