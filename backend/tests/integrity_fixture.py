"""Test-only demo courses for the integrity board.

The application ships an empty integrity board until real submissions are
registered. Tests that need the synthetic drill-down install these courses
and remove them afterwards.
"""

from typing import Any

from app.profassist.integrity_board import register_course, unregister_course
from app.profassist.integrity_docs import reset_library

DEMO_COURSES: list[dict[str, Any]] = [
    {
        "code": "MAAI 903",
        "slug": "MAAI903",
        "title": "AI Solutions Design & MLOps",
        "assignments": [
            {
                "number": "1",
                "title": "Workshops",
                "groups": ["A", "B", "C", "D", "E"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "B",
                        "percent": 86,
                        "passages": [
                            {
                                "id": "m1",
                                "percent": 92,
                                "common": False,
                                "writing": "Medium",
                                "left": "The shared draft still contains the typo sustanability.",
                                "right": "The shared draft still contains the typo sustanability.",
                            },
                            {
                                "id": "m2",
                                "percent": 78,
                                "common": False,
                                "writing": "Low",
                                "left": "We interviewed facilities staff and mapped meters to floors.",
                                "right": "We interviewed facilities staff and mapped meters to floors.",
                            },
                            {
                                "id": "m2b",
                                "percent": 100,
                                "common": True,
                                "writing": "Low",
                                "left": "The brief asks each group to name one campus process and measure it for four weeks.",
                                "right": "The brief asks each group to name one campus process and measure it for four weeks.",
                            },
                        ],
                    },
                    {
                        "left": "C",
                        "right": "D",
                        "percent": 48,
                        "passages": [
                            {
                                "id": "m3",
                                "percent": 70,
                                "common": True,
                                "writing": "Low",
                                "left": "The brief asks for a measurable operational problem.",
                                "right": "The brief asks for a measurable operational problem.",
                            },
                            {
                                "id": "m3b",
                                "percent": 48,
                                "common": False,
                                "writing": "Low",
                                "left": "Peak use follows the afternoon class change.",
                                "right": "Peak use follows the afternoon class change.",
                            },
                        ],
                    },
                ],
            },
            {
                "number": "2",
                "title": "Architecture report",
                "groups": ["A", "B", "C", "D", "E"],
                "pairs": [
                    {
                        "left": "B",
                        "right": "E",
                        "percent": 62,
                        "passages": [
                            {
                                "id": "m4",
                                "percent": 64,
                                "common": False,
                                "writing": "Medium",
                                "left": "The rollback plan names who to call if the API fails.",
                                "right": "The rollback plan names who to call if the API fails.",
                            }
                        ],
                    }
                ],
            },
            {
                "number": "3",
                "title": "Group project",
                "groups": ["A", "B", "C", "D", "E", "F"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "C",
                        "percent": 22,
                        "passages": [],
                    },
                    {
                        "left": "D",
                        "right": "F",
                        "percent": 18,
                        "passages": [
                            {
                                "id": "m5",
                                "percent": 18,
                                "common": False,
                                "writing": "High",
                                "left": "The system optimises throughput across heterogeneous nodes.",
                                "right": "The system optimises throughput across heterogeneous nodes.",
                            }
                        ],
                    },
                ],
            },
        ],
    },
    {
        "code": "MAAI 901",
        "slug": "MAAI901",
        "title": "Applied Machine Learning",
        "assignments": [
            {
                "number": "1",
                "title": "Problem set",
                "groups": ["A", "B", "C", "D"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "C",
                        "percent": 78,
                        "passages": [
                            {
                                "id": "m6",
                                "percent": 81,
                                "common": False,
                                "writing": "High",
                                "left": "The loss falls after epoch four because the learning rate was halved.",
                                "right": "The loss falls after epoch four because the learning rate was halved.",
                            }
                        ],
                    }
                ],
            },
            {
                "number": "2",
                "title": "Lab notes",
                "groups": ["A", "B", "C", "D"],
                "pairs": [
                    {
                        "left": "B",
                        "right": "D",
                        "percent": 41,
                        "passages": [
                            {
                                "id": "m7",
                                "percent": 66,
                                "common": True,
                                "writing": "Low",
                                "left": "Students record the seed and the data version in the lab note.",
                                "right": "Students record the seed and the data version in the lab note.",
                            },
                            {
                                "id": "m7b",
                                "percent": 41,
                                "common": False,
                                "writing": "Low",
                                "left": "The lab note stops before the error bars.",
                                "right": "The lab note stops before the error bars.",
                            },
                        ],
                    }
                ],
            },
        ],
    },
]


def install() -> None:
    """Register the demo courses and rebuild the document library."""
    for course in DEMO_COURSES:
        register_course(course)
    reset_library()


def remove() -> None:
    """Unregister the demo courses and rebuild the document library."""
    for course in DEMO_COURSES:
        unregister_course(course["slug"])
    reset_library()
