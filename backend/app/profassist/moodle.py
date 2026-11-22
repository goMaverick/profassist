"""Moodle connector.

``MOODLE_MODE=fake`` (the default) serves a seeded catalogue and records pushes
locally. ``MOODLE_MODE=real`` uses the same method names against the read-only
Moodle REST API plus an LTI 1.3 launch payload. The real client is not called
unless that flag and its credentials are set.
"""

import os
from typing import Any, Protocol

from app.profassist.config import moodle_mode
from app.profassist.errors import ProfassistError

LTI_CONTEXT = "https://purl.imsglobal.org/spec/lti/claim/context"
LTI_ROLES = "https://purl.imsglobal.org/spec/lti/claim/roles"

_METHOD = (
    "We interviewed facilities staff and mapped meters to floors. A limitation is that "
    "weekend readings were missing, therefore the trend is only reliable on weekdays."
)

SUBMISSIONS = [
    {
        "id": "sub-a",
        "assignment_id": "asg-901",
        "group_name": "Group A",
        "topic": "campus energy dashboard",
        "text": (
            "Student: Sara Al Maktoum\n"
            "Student ID: 8881001\n"
            "Email: sara.almaktoum@student.uowd.ac.ae\n\n"
            "Introduction\n"
            "Our group designed a campus energy dashboard for the main block. "
            "The baseline load is 42.7 kWh during the teaching day. We chose this use case "
            "because the brief asks for a measurable operational problem.\n\n"
            "Method\n"
            f"{_METHOD} The shared draft still contains the typo sustanability.\n\n"
            "Findings\n"
            "The dashboard would cut unnoticed overnight load. Evidence from the meter export "
            "shows the 42.7 kWh plateau. We recommend a weekly review with the facilities team."
        ),
    },
    {
        "id": "sub-b",
        "assignment_id": "asg-901",
        "group_name": "Group B18",
        "topic": "campus energy dashboard",
        "text": (
            "Student: Omar Haddad\n"
            "Student ID: 8881002\n"
            "Email: omar.haddad@student.uowd.ac.ae\n\n"
            "Introduction\n"
            "This report also looks at campus energy, but from the library wing rather than the main block.\n\n"
            "Method\n"
            f"{_METHOD} The shared draft still contains the typo sustanability and the figure 42.7.\n\n"
            "Findings\n"
            "The library wing differs because opening hours extend later. Because the evidence is "
            "partial we stay cautious about a campus-wide claim."
        ),
    },
    {
        "id": "sub-c",
        "assignment_id": "asg-901",
        "group_name": "Group C",
        "topic": "campus energy dashboard",
        "text": (
            "Student: Noor Rahman\n"
            "Student ID: 8881003\n"
            "Email: noor.rahman@student.uowd.ac.ae\n\n"
            "Introduction\n"
            "We studied water use in the student hub while staying inside the campus-operations brief.\n\n"
            "Method\n"
            "Sensor counts were taken at morning and evening for five days. No shared meter figure is used.\n\n"
            "Findings\n"
            "Peak use follows class changeover. A limitation is the small sample, therefore we do not "
            "generalise beyond the hub."
        ),
    },
]

STUDENTS = [
    {
        "id": "stu-1",
        "course_id": "mdl-maai903",
        "display_name": "Sara Al Maktoum",
        "email": "sara.almaktoum@student.uowd.ac.ae",
        "student_number": "8881001",
    },
    {
        "id": "stu-2",
        "course_id": "mdl-maai903",
        "display_name": "Omar Haddad",
        "email": "omar.haddad@student.uowd.ac.ae",
        "student_number": "8881002",
    },
    {
        "id": "stu-3",
        "course_id": "mdl-maai903",
        "display_name": "Noor Rahman",
        "email": "noor.rahman@student.uowd.ac.ae",
        "student_number": "8881003",
    },
    {
        "id": "stu-4",
        "course_id": "mdl-maai903",
        "display_name": "Layla Karim",
        "email": "layla.karim@student.uowd.ac.ae",
        "student_number": "8881004",
    },
]

CATALOG: dict[str, Any] = {
    "courses": [
        {
            "id": "mdl-maai903",
            "code": "MAAI903",
            "title": "AI Solutions Design & MLOps",
            "term": "2026",
        }
    ],
    "assignments": [
        {
            "id": "asg-901",
            "course_id": "mdl-maai903",
            "name": "Group report 1",
        }
    ],
    "students": STUDENTS,
    "submissions": SUBMISSIONS,
}

LECTURE_NOTE = """
Course learning outcome one. Explain how an LLM agent differs from a trained machine learning model.
Course learning outcome two. Design an assessment that shows whether students met that outcome.
Course learning outcome three. Give feedback that quotes the student's own evidence.

An assessment brief should name the audience, the artefact, and the course learning outcome it evidences.
Rubric levels used in this course are beginning, developing, proficient, and advanced.
Slides should state one idea per slide and cite the lecture note they came from.
Feedback should be short, specific, and free of exclamation marks.
A limitation next to the evidence is better than a vague compliment.
""".strip()

CLOS = [
    "Explain how an LLM agent differs from a trained machine learning model.",
    "Design an assessment that shows whether students met that outcome.",
    "Give feedback that quotes the student's own evidence.",
]


def parse_lti_launch(claims: dict[str, Any]) -> dict[str, Any]:
    """Read an LTI 1.3 id_token claim set. Missing fields stay empty."""
    context = claims.get(LTI_CONTEXT) or {}
    if not isinstance(context, dict):
        context = {}
    roles = claims.get(LTI_ROLES) or claims.get("roles") or []
    return {
        "issuer": claims.get("iss"),
        "subject": claims.get("sub"),
        "email": claims.get("email"),
        "course_external_id": context.get("id") or claims.get("course_id"),
        "course_title": context.get("title") or claims.get("course_title"),
        "roles": roles,
    }


class MoodleConnector(Protocol):
    mode: str

    def list_courses(self) -> list[dict[str, Any]]: ...

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_assignments(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_submissions(self, assignment_external_id: str) -> list[dict[str, Any]]: ...

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]: ...

    def push(self, item: dict[str, Any]) -> dict[str, Any]: ...


class FakeMoodleConnector:
    mode = "fake"

    def list_courses(self) -> list[dict[str, Any]]:
        return list(CATALOG["courses"])

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]:
        return [row for row in STUDENTS if row["course_id"] == course_external_id]

    def list_assignments(self, course_external_id: str) -> list[dict[str, Any]]:
        return [row for row in CATALOG["assignments"] if row["course_id"] == course_external_id]

    def list_submissions(self, assignment_external_id: str) -> list[dict[str, Any]]:
        return [row for row in SUBMISSIONS if row["assignment_id"] == assignment_external_id]

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_lti_launch(claims)
        parsed["mode"] = self.mode
        if not parsed["course_external_id"]:
            parsed["course_external_id"] = "mdl-maai903"
            parsed["course_title"] = "AI Solutions Design & MLOps"
        parsed["note"] = "Fake LTI 1.3 launch. Moodle was not contacted."
        return parsed

    def push(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": "fake",
            "accepted": True,
            "moodle_response": "Recorded in ProfAssist. Moodle was not contacted.",
            "item": item,
        }


class RealMoodleConnector:
    """Same shape as the fake connector, aimed at Moodle's REST web service."""

    mode = "real"

    def __init__(self) -> None:
        self.base = os.getenv("MOODLE_BASE_URL", "").rstrip("/")
        self.token = os.getenv("MOODLE_WS_TOKEN", "")

    def _ws(self, function: str, params: dict[str, Any]) -> Any:
        if not self.base or not self.token:
            raise ProfassistError(
                503,
                "MOODLE_MODE=real needs MOODLE_BASE_URL and MOODLE_WS_TOKEN. "
                "Leave MOODLE_MODE=fake until the university connection exists.",
            )
        import httpx

        url = f"{self.base}/webservice/rest/server.php"
        query: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        response = httpx.get(url, params=query, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("exception"):
            raise ProfassistError(502, f"Moodle refused {function}: {payload.get('message')}")
        return payload

    def list_courses(self) -> list[dict[str, Any]]:
        rows = self._ws("core_course_get_courses", {})
        return [
            {
                "id": str(row.get("id")),
                "code": row.get("shortname"),
                "title": row.get("fullname"),
                "term": "",
            }
            for row in rows
            if isinstance(row, dict)
        ]

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]:
        rows = self._ws("core_enrol_get_enrolled_users", {"courseid": course_external_id})
        return [
            {
                "id": str(row.get("id")),
                "course_id": course_external_id,
                "display_name": row.get("fullname"),
                "email": row.get("email"),
                "student_number": str(row.get("id")),
            }
            for row in rows
            if isinstance(row, dict)
        ]

    def list_assignments(self, course_external_id: str) -> list[dict[str, Any]]:
        payload = self._ws("mod_assign_get_assignments", {"courseids[0]": course_external_id})
        found = []
        for course in payload.get("courses", []) if isinstance(payload, dict) else []:
            for assignment in course.get("assignments", []):
                found.append(
                    {
                        "id": str(assignment.get("id")),
                        "course_id": course_external_id,
                        "name": assignment.get("name"),
                    }
                )
        return found

    def list_submissions(self, assignment_external_id: str) -> list[dict[str, Any]]:
        payload = self._ws(
            "mod_assign_get_submissions",
            {"assignmentids[0]": assignment_external_id},
        )
        found = []
        for assignment in payload.get("assignments", []) if isinstance(payload, dict) else []:
            for submission in assignment.get("submissions", []):
                text = ""
                for plugin in submission.get("plugins", []):
                    for field in plugin.get("editorfields", []) or []:
                        text += field.get("text") or ""
                found.append(
                    {
                        "id": str(submission.get("id")),
                        "assignment_id": assignment_external_id,
                        "group_name": f"User {submission.get('userid')}",
                        "topic": "moodle",
                        "text": text,
                    }
                )
        return found

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_lti_launch(claims)
        parsed["mode"] = self.mode
        if not parsed["course_external_id"]:
            raise ProfassistError(400, "LTI launch is missing the context id claim.")
        return parsed

    def push(self, item: dict[str, Any]) -> dict[str, Any]:
        # The university connection is read-only in the architecture. A real grade
        # write needs a separate, explicitly enabled webservice. Until then we
        # refuse rather than pretending Moodle accepted the grade.
        raise ProfassistError(
            501,
            "The real Moodle connector is read-only (LTI 1.3 launch and REST reads). "
            "Grade push is not enabled. Use MOODLE_MODE=fake to record an approved push locally.",
        )


def get_connector() -> MoodleConnector:
    if moodle_mode() == "real":
        return RealMoodleConnector()
    return FakeMoodleConnector()
