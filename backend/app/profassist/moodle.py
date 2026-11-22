"""Moodle connector.

``MOODLE_MODE=fake`` (the default) serves a seeded catalogue and records pushes
locally. ``MOODLE_MODE=real`` uses the same method names against the read-only
Moodle REST API plus an LTI 1.3 launch payload. The real client is not called
unless that flag and its credentials are set.
"""

import os
from pathlib import Path
from typing import Any, Protocol

from app.profassist.config import moodle_mode, moodle_push_enabled
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
        "group_name": "Group B",
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
            "kind": "assignment",
            "rubric": [],
        }
    ],
    "workshops": [
        {
            "id": "ws-901",
            "course_id": "mdl-maai903",
            "name": "Peer review of the design brief",
            "kind": "workshop",
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


def _sample(name: str) -> bytes:
    return (Path(__file__).parent / "samples" / name).read_bytes()


_SAMPLE_FILES: dict[str, list[tuple[str, str]]] = {
    "sub-a": [
        (
            "group-a-report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("group-a-code.zip", "application/zip"),
        ("meter-chart.png", "image/png"),
    ],
    "sub-b": [("group-b-report.pdf", "application/pdf")],
    "sub-c": [("group-c-report.txt", "text/plain")],
    "wsub-1": [
        (
            "workshop-brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    ],
}

WORKSHOP_SUBMISSIONS = [
    {
        "id": "wsub-1",
        "assignment_id": "ws-901",
        "group_name": "Group A",
        "author_id": "stu-1",
        "topic": "design brief",
        "text": (
            "The artefact is a one-page design brief for a campus operations assistant. "
            "It names the audience, the artefact, and the course learning outcome it evidences."
        ),
        "peer_reviews": [
            {
                "reviewer": "Group B",
                "text": "The brief names the audience. The outcome is only partly shown.",
                "scores": {"CLO 1": "developing"},
            },
            {
                "reviewer": "Group C",
                "text": "Clear artefact. I would ask the author to state a limitation.",
                "scores": {"CLO 1": "proficient"},
            },
        ],
    }
]


def _with_files(row: dict[str, Any]) -> dict[str, Any]:
    files = []
    for filename, content_type in _SAMPLE_FILES.get(row["id"], []):
        files.append(
            {"filename": filename, "content_type": content_type, "data": _sample(filename)}
        )
    copied = dict(row)
    copied["files"] = files
    copied.setdefault("peer_reviews", [])
    copied.setdefault("author_id", "")
    return copied


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

    def list_workshops(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_workshop_submissions(self, workshop_external_id: str) -> list[dict[str, Any]]: ...

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
        return [
            _with_files(row)
            for row in SUBMISSIONS
            if row["assignment_id"] == assignment_external_id
        ]

    def list_workshops(self, course_external_id: str) -> list[dict[str, Any]]:
        return [row for row in CATALOG["workshops"] if row["course_id"] == course_external_id]

    def list_workshop_submissions(self, workshop_external_id: str) -> list[dict[str, Any]]:
        return [
            _with_files(row)
            for row in WORKSHOP_SUBMISSIONS
            if row["assignment_id"] == workshop_external_id
        ]

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
                        "kind": "assignment",
                        "cmid": str(assignment.get("cmid") or ""),
                        "rubric": self._rubric(str(assignment.get("cmid") or "")),
                    }
                )
        return found

    def _rubric(self, cmid: str) -> list[dict[str, Any]]:
        if not cmid:
            return []
        try:
            payload = self._ws(
                "core_grading_get_definitions",
                {"cmids[0]": cmid, "areaname": "submissions", "activeonly": 1},
            )
        except ProfassistError:
            return []
        criteria = []
        areas = payload.get("areas", []) if isinstance(payload, dict) else []
        for area in areas:
            for definition in area.get("definitions", []) or []:
                form = definition.get("rubric") or definition.get("guide") or {}
                for ordinal, criterion in enumerate(form.get("criteria", []) or [], start=1):
                    levels = {}
                    labels = ("beginning", "developing", "proficient", "advanced")
                    raw_levels = criterion.get("levels") or []
                    for index, level in enumerate(raw_levels[:4]):
                        levels[labels[index]] = (
                            level.get("definition") or level.get("description") or ""
                        )
                    criteria.append(
                        {
                            "name": criterion.get("description") or f"Criterion {ordinal}",
                            "weight": 1,
                            "levels": levels,
                        }
                    )
        return criteria

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
                        "author_id": str(submission.get("userid") or ""),
                        "topic": "moodle",
                        "text": text,
                        "peer_reviews": [],
                        "files": self._files_from_plugins(submission),
                    }
                )
        return found

    def list_workshops(self, course_external_id: str) -> list[dict[str, Any]]:
        payload = self._ws(
            "mod_workshop_get_workshops_by_courses", {"courseids[0]": course_external_id}
        )
        rows = payload.get("workshops", []) if isinstance(payload, dict) else payload
        return [
            {
                "id": str(row.get("id")),
                "course_id": course_external_id,
                "name": row.get("name"),
                "kind": "workshop",
            }
            for row in rows
            if isinstance(row, dict)
        ]

    def list_workshop_submissions(self, workshop_external_id: str) -> list[dict[str, Any]]:
        payload = self._ws("mod_workshop_get_submissions", {"workshopid": workshop_external_id})
        submissions = payload.get("submissions", []) if isinstance(payload, dict) else []
        found = []
        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            reviews = []
            try:
                assessments = self._ws(
                    "mod_workshop_get_assessments",
                    {"submissionid": submission.get("id")},
                )
            except ProfassistError:
                assessments = {}
            rows = assessments.get("assessments", []) if isinstance(assessments, dict) else []
            for review in rows:
                if isinstance(review, dict):
                    reviews.append(
                        {
                            "reviewer": f"User {review.get('reviewerid')}",
                            "text": review.get("feedbackauthor") or "",
                            "scores": {},
                        }
                    )
            found.append(
                {
                    "id": str(submission.get("id")),
                    "assignment_id": workshop_external_id,
                    "group_name": f"User {submission.get('authorid')}",
                    "author_id": str(submission.get("authorid") or ""),
                    "topic": "workshop",
                    "text": submission.get("content") or submission.get("title") or "",
                    "peer_reviews": reviews,
                    "files": self._files_from_urls(submission.get("attachmentfiles") or []),
                }
            )
        return found

    def _files_from_plugins(self, submission: dict[str, Any]) -> list[dict[str, Any]]:
        files = []
        for plugin in submission.get("plugins", []) or []:
            for area in plugin.get("fileareas", []) or []:
                for item in area.get("files", []) or []:
                    filename = item.get("filename") or "attachment"
                    fileurl = item.get("fileurl") or ""
                    if not fileurl or filename == ".":
                        continue
                    files.append(
                        {
                            "filename": filename,
                            "content_type": "application/octet-stream",
                            "data": self._download(fileurl),
                        }
                    )
        return files

    def _files_from_urls(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        files = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            fileurl = item.get("fileurl") or ""
            if not fileurl:
                continue
            files.append(
                {
                    "filename": item.get("filename") or "attachment",
                    "content_type": "application/octet-stream",
                    "data": self._download(fileurl),
                }
            )
        return files

    def _download(self, fileurl: str) -> bytes:
        import httpx

        url = fileurl
        if "token=" not in url:
            join = "&" if "?" in url else "?"
            url = f"{url}{join}token={self.token}"
        response = httpx.get(url, timeout=60.0)
        response.raise_for_status()
        return response.content

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_lti_launch(claims)
        parsed["mode"] = self.mode
        if not parsed["course_external_id"]:
            raise ProfassistError(400, "LTI launch is missing the context id claim.")
        return parsed

    def push(self, item: dict[str, Any]) -> dict[str, Any]:
        if not moodle_push_enabled():
            raise ProfassistError(
                501,
                "Real grade push is off. Set MOODLE_PUSH_ENABLED=true only after the "
                "service account has mod/assign:grade. Until then the push is refused.",
            )
        if item.get("type") != "grade":
            raise ProfassistError(400, "Only an approved grade can be pushed to Moodle.")
        self._ws_post(
            "mod_assign_save_grade",
            {
                "assignmentid": item.get("assignment_external_id") or "",
                "userid": item.get("author_external_id") or "",
                "grade": item.get("grade") or 0,
                "attemptnumber": -1,
                "addattempt": 0,
                "workflowstate": "",
                "applytoall": 0,
                "plugindata[assignfeedbackcomments_editor][text]": item.get("feedback") or "",
                "plugindata[assignfeedbackcomments_editor][format]": 1,
            },
        )
        return {
            "mode": "real",
            "accepted": True,
            "moodle_response": "mod_assign_save_grade accepted the approved grade.",
            "item": {key: value for key, value in item.items() if key != "files"},
        }

    def _ws_post(self, function: str, params: dict[str, Any]) -> Any:
        if not self.base or not self.token:
            raise ProfassistError(
                503,
                "MOODLE_MODE=real needs MOODLE_BASE_URL and MOODLE_WS_TOKEN.",
            )
        import httpx

        url = f"{self.base}/webservice/rest/server.php"
        body = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        response = httpx.post(url, data=body, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("exception"):
            raise ProfassistError(502, f"Moodle refused {function}: {payload.get('message')}")
        return payload


def get_connector() -> MoodleConnector:
    if moodle_mode() == "real":
        return RealMoodleConnector()
    return FakeMoodleConnector()
