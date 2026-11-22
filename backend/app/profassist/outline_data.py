"""Seed content for the MAAI 903 subject outline. The professor can edit every field."""

POLICIES = [
    {
        "key": "academic_integrity",
        "title": "Academic integrity",
        "body": (
            "Plagiarism and cheating are serious offences. Students submit written work through "
            "the integrity system named in the first lecture. A flag in ProfAssist is evidence for "
            "a conversation, not a verdict."
        ),
    },
    {
        "key": "attendance",
        "title": "Attendance",
        "body": (
            "Students attend the scheduled lecture and workshop. Missing the attendance rule in "
            "the faculty policy can lead to a fail even when the composite mark is a pass."
        ),
    },
    {
        "key": "lecture_capture",
        "title": "Lecture capture",
        "body": (
            "Lectures may be recorded for students enrolled in the subject. Recordings stay on the "
            "university platform and are not a substitute for the workshop."
        ),
    },
    {
        "key": "sustainability",
        "title": "Sustainability",
        "body": (
            "Workshop briefs are published on the learning site. Printed copies are not handed out "
            "in class. Submit electronic copies."
        ),
    },
]


def demo_outline() -> dict:
    """The published MAAI 903 shape: basics, outcomes, weeks, readings, and assessments."""
    plos = [
        (
            "PLO1",
            "Evaluate challenges and formulate AI strategies that meet ethical and regulatory rules.",
        ),
        ("PLO2", "Design practical AI solutions with modern machine learning and MLOps practice."),
        ("PLO3", "Judge which AI models fit a data type and an industry setting."),
        ("PLO4", "Implement automated solutions across industries."),
        ("PLO5", "Run an applied AI project with methodological care."),
        ("PLO6", "Communicate technical decisions and apply ethical reasoning."),
    ]
    clos = [
        (
            "LO1",
            "Design end-to-end AI solution architectures for a real need.",
            ["PLO1", "PLO2", "PLO3", "PLO4", "PLO6"],
        ),
        (
            "LO2",
            "Implement reproducible machine-learning workflows with MLOps tools.",
            ["PLO2", "PLO3", "PLO4", "PLO5"],
        ),
        (
            "LO3",
            "Evaluate scalability, reliability, and maintainability in production.",
            ["PLO1", "PLO2", "PLO3", "PLO5"],
        ),
        (
            "LO4",
            "Apply CI/CD and versioning to data, models, and pipelines.",
            ["PLO2", "PLO3", "PLO4", "PLO5"],
        ),
        (
            "LO5",
            "Assess ethical, regulatory, and operational risk at scale.",
            ["PLO1", "PLO4", "PLO6"],
        ),
        (
            "LO6",
            "Explain design decisions to technical and non-technical people.",
            ["PLO5", "PLO6"],
        ),
    ]
    weeks = [
        (
            1,
            "AI systems design overview and problem scoping",
            ["LO1"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            2,
            "Solution architecture and the ML lifecycle",
            ["LO1"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            3,
            "Data and model versioning",
            ["LO2", "LO4"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            4,
            "Reproducible experimentation and tracking",
            ["LO2"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            5,
            "Model deployment with APIs and containers",
            ["LO2", "LO3"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            6,
            "CI/CD for machine learning",
            ["LO2", "LO4"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (
            7,
            "Monitoring, drift, and feedback loops",
            ["LO3"],
            "Lecture / workshop",
            "F2F",
            "Solution architecture report (S)",
        ),
        (
            8,
            "Scalability and maintainability in production",
            ["LO3", "LO4"],
            "Lecture / workshop",
            "F2F",
            "Workshop (F)",
        ),
        (9, "MLOps tool ecosystems", ["LO2", "LO3"], "Lecture / workshop", "F2F", "Workshop (F)"),
        (10, "Governance, risk, and ethics", ["LO5"], "Lecture / workshop", "F2F", "Workshop (F)"),
        (
            11,
            "Review and project presentations",
            ["LO6"],
            "Presentation",
            "F2F",
            "Group project (S)",
        ),
    ]
    readings = [
        "Burkov, Andriy. Machine Learning Engineering. True Positive, 2020.",
        "Huyen, Chip. Designing Machine Learning Systems. O'Reilly, 2022.",
        "Osipov, Carl. MLOps Engineering at Scale. Manning, 2022.",
        "Hapke, Hannes, and Catherine Nelson. Building Machine Learning Pipelines. O'Reilly, 2020.",
        "Gift, Noah, and Alfredo Deza. Practical MLOps. O'Reilly, 2021.",
    ]
    tasks = [
        {
            "number": "A1",
            "name": "Workshops",
            "task_type": "Individual",
            "weight": 25,
            "due": "Throughout the semester",
            "lo_codes": ["LO2", "LO3", "LO4"],
            "brief": "Practical workshop tasks released on the learning site. No printed copies.",
            "criteria": [
                {
                    "name": "Quality of the solution",
                    "weight": 20,
                    "levels": _levels("the solution"),
                },
                {
                    "name": "Accuracy of the implementation",
                    "weight": 30,
                    "levels": _levels("the implementation"),
                },
                {"name": "Quality of the results", "weight": 30, "levels": _levels("the results")},
                {
                    "name": "Clarity of the documentation",
                    "weight": 20,
                    "levels": _levels("the documentation"),
                },
            ],
        },
        {
            "number": "A2",
            "name": "Solution architecture report",
            "task_type": "Individual",
            "weight": 25,
            "due": "Week 7",
            "lo_codes": ["LO1", "LO3", "LO5"],
            "brief": "A technical report of at most 2,500 words with an architecture diagram, data strategy, deployment plan, and ethical risks.",
            "criteria": [
                {"name": "Problem definition", "weight": 15, "levels": _levels("the problem")},
                {"name": "Solution design", "weight": 25, "levels": _levels("the architecture")},
                {"name": "Data strategy", "weight": 20, "levels": _levels("the pipeline")},
                {"name": "Deployment plan", "weight": 15, "levels": _levels("the deployment")},
                {"name": "Ethical risk", "weight": 15, "levels": _levels("the ethical risks")},
                {"name": "Presentation", "weight": 10, "levels": _levels("the writing")},
            ],
        },
        {
            "number": "A3",
            "name": "Group project",
            "task_type": "Group",
            "weight": 40,
            "due": "Week 11",
            "lo_codes": ["LO1", "LO2", "LO3", "LO4", "LO6"],
            "brief": "A working pipeline, a short demo, and deployment notes that apply the architecture report.",
            "criteria": [
                {
                    "name": "Pipeline implementation",
                    "weight": 30,
                    "levels": _levels("the pipeline"),
                },
                {"name": "Use of MLOps tools", "weight": 20, "levels": _levels("the tools")},
                {
                    "name": "Deployment documentation",
                    "weight": 20,
                    "levels": _levels("the documentation"),
                },
            ],
        },
        {
            "number": "A4",
            "name": "Communication and reflection video",
            "task_type": "Individual",
            "weight": 10,
            "due": "Week 12",
            "lo_codes": ["LO5", "LO6"],
            "brief": "A short video that explains the design choices and the operational risks to a mixed audience.",
            "criteria": [
                {
                    "name": "Clarity for a mixed audience",
                    "weight": 60,
                    "levels": _levels("the explanation"),
                },
                {"name": "Reflection on risk", "weight": 40, "levels": _levels("the reflection")},
            ],
        },
    ]
    return {
        "basics": {
            "name": "AI Solutions Design & MLOps",
            "code": "MAAI 903",
            "credit_points": 6,
            "session": "Autumn",
            "year": 2026,
            "duration": "11 weeks",
            "prerequisites": "MAAI 901, MAAI 902",
            "delivery_mode": "F2F",
            "section": "Autumn",
            "equivalent": "Nil",
        },
        "lecture": {
            "day": "Thursday",
            "time": "18:00-22:00",
            "location": "3.48 Classroom B",
            "educator_name": "Dr Patrick Mukala",
            "office": "3rd floor, new building",
            "email": "patrickmukala@uowdubai.ac.ae",
            "consultation": "Wednesday 09:00-11:00 and Thursday 10:00-12:00, WebEx, email, or in person.",
        },
        "description": (
            "This subject is about building, deploying, and looking after AI systems in production. "
            "Students design a solution, automate the workflow, and keep data and models reproducible."
        ),
        "program": "Master of Applied Artificial Intelligence",
        "plos": [{"code": code, "text": text} for code, text in plos],
        "clos": [{"code": code, "text": text, "plos": mapped} for code, text, mapped in clos],
        "weeks": [
            {
                "week": week,
                "topic": topic,
                "lo_codes": los,
                "session_type": session,
                "delivery": delivery,
                "assessment_note": note,
            }
            for week, topic, los, session, delivery, note in weeks
        ],
        "readings": readings,
        "tasks": tasks,
        "policies": POLICIES,
    }


def _levels(topic: str) -> dict[str, str]:
    return {
        "beginning": f"Names {topic} without evidence.",
        "developing": f"Partly shows {topic}.",
        "proficient": f"Shows {topic} with a concrete example.",
        "advanced": f"Shows {topic} and states a limitation.",
    }


def empty_outline() -> dict:
    seed = demo_outline()
    return {
        "basics": {
            key: "" if not isinstance(value, int) else 0 for key, value in seed["basics"].items()
        },
        "lecture": dict.fromkeys(seed["lecture"], ""),
        "description": "",
        "program": "",
        "plos": [],
        "clos": [],
        "weeks": [],
        "readings": [],
        "tasks": [],
        "policies": POLICIES,
    }
