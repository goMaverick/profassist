"""Moodle connector.

``MOODLE_MODE=real`` (the default) talks to the Moodle REST API and an LTI 1.3
launch payload. ``MOODLE_MODE=fake`` must be set explicitly for automated tests;
it serves a seeded catalogue and records pushes locally. A missing Moodle
configuration is an explicit error, never a silent switch to fake data.
"""

import re
import time
from pathlib import Path
from typing import Any, Protocol

from app.profassist.config import moodle_mode, moodle_push_enabled
from app.profassist.errors import ProfassistError

_TOKEN_PATTERN = re.compile(r"(?i)\b(wstoken|token)=([^&\s\"'<>]+)")


def _redact(value: Any) -> str:
    """Strip a Moodle web-service token out of anything stored or returned."""
    if value is None:
        return ""
    return _TOKEN_PATTERN.sub(lambda match: f"{match.group(1)}=***", str(value))


class MoodleConnectionSpec:
    """One university's Moodle address, token, and scope.

    The connector never invents a token: an empty spec falls back to the
    process environment only for a single-campus deployment.
    """

    def __init__(
        self,
        base_url: str = "",
        token: str = "",
        course_scope: dict[str, Any] | None = None,
        push_enabled: bool = False,
        source: str = "none",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.course_scope = dict(course_scope or {})
        self.push_enabled = bool(push_enabled)
        self.source = source

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)


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
    copied = dict(row)
    if not copied.get("files"):
        files = []
        for filename, content_type in _SAMPLE_FILES.get(row["id"], []):
            files.append(
                {"filename": filename, "content_type": content_type, "data": _sample(filename)}
            )
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

    def site_info(self) -> dict[str, Any]: ...

    def list_courses(self) -> list[dict[str, Any]]: ...

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_assignments(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_submissions(
        self, assignment_external_id: str, course_external_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def list_workshops(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def list_workshop_submissions(self, workshop_external_id: str) -> list[dict[str, Any]]: ...

    def list_activity(self, course_external_id: str) -> list[dict[str, Any]]: ...

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]: ...

    def push(self, item: dict[str, Any]) -> dict[str, Any]: ...


class FakeMoodleConnector:
    mode = "fake"

    def site_info(self) -> dict[str, Any]:
        return {
            "site_url": "https://moodle.example.edu",
            "site_name": "ProfAssist Demo Moodle",
            "release": "4.5 (Build: 20241007)",
            "version": "2024100700",
            "siteid": "1",
            "userid": "2",
            "username": "wsuser",
            "capabilities": {
                "functions": ["core_course_get_courses", "mod_assign_get_submissions"],
                "downloadfiles": True,
                "uploadfiles": False,
                "enablecompletion": True,
            },
            "warnings": [],
        }

    def list_courses(self) -> list[dict[str, Any]]:
        return list(CATALOG["courses"])

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]:
        return [row for row in STUDENTS if row["course_id"] == course_external_id]

    def list_assignments(self, course_external_id: str) -> list[dict[str, Any]]:
        return [row for row in CATALOG["assignments"] if row["course_id"] == course_external_id]

    def list_submissions(
        self, assignment_external_id: str, course_external_id: str | None = None
    ) -> list[dict[str, Any]]:
        del course_external_id
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

    def list_activity(self, course_external_id: str) -> list[dict[str, Any]]:
        """The fake catalogue has no activity log, so nothing is scored."""
        del course_external_id
        return []

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

    def stage_course_work(
        self,
        *,
        course: dict[str, Any],
        students: list[dict[str, Any]],
        assignment: dict[str, Any],
        submissions: list[dict[str, Any]],
    ) -> None:
        """Remember a published assignment so the next fake sync can pull it.

        Nothing is sent over the network. The rows live in this process only.
        """
        if not any(row.get("id") == course["id"] for row in CATALOG["courses"]):
            CATALOG["courses"].append(course)
        for student in students:
            if not any(row.get("id") == student["id"] for row in STUDENTS):
                STUDENTS.append(student)
        if not any(row.get("id") == assignment["id"] for row in CATALOG["assignments"]):
            CATALOG["assignments"].append(assignment)
        for submission in submissions:
            if any(row.get("id") == submission["id"] for row in SUBMISSIONS):
                continue
            SUBMISSIONS.append(submission)


_LEVEL_LABELS = ("beginning", "developing", "proficient", "advanced")

_RETRY_STATUS = frozenset({429, 502, 503, 504})

_ERROR_STATUS = {
    "required_capability_exception": 403,
    "accessexception": 403,
    "nopermissions": 403,
    "invalid_parameter_exception": 422,
    "invalidrecord": 422,
    "webservice_access_exception": 503,
    "servicerequireslogin": 503,
    "servicenotavailable": 503,
    "moodle_exception": 503,
}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _moodle_error(function: str, payload: dict[str, Any]) -> ProfassistError:
    """Map a Moodle JSON error to a status the caller can act on.

    Permission problems are 403, bad inputs are 422, and configuration or
    downtime problems are 503. A configuration error is never a 502, and the
    token never survives redaction.
    """
    code = str(payload.get("errorcode") or payload.get("exception") or "").strip()
    message = (
        payload.get("message")
        or payload.get("debuginfo")
        or code
        or "Moodle refused the call without a reason."
    )
    return ProfassistError(
        _ERROR_STATUS.get(code, 503),
        _redact(f"Moodle refused {function}: {message}"),
    )


class RealMoodleConnector:
    """Same shape as the fake connector, aimed at Moodle's REST web service.

    Each instance carries one university's base URL and token. The process
    environment is only a fallback for a deployment that has no per-org row yet.
    """

    mode = "real"

    def __init__(self, spec: MoodleConnectionSpec | None = None) -> None:
        from app.profassist.config import moodle_base_url, moodle_ws_token

        spec = spec or MoodleConnectionSpec()
        # Never pair an org's base URL with the process-wide token, or the other
        # way round. The env seed applies only when the spec is completely empty.
        if spec.base_url or spec.token:
            self.base = spec.base_url.rstrip("/")
            self.token = spec.token
        else:
            self.base = moodle_base_url()
            self.token = moodle_ws_token()
        self.course_scope = dict(spec.course_scope or {})
        self.push_enabled = bool(spec.push_enabled)
        self.source = spec.source
        self.warnings: list[dict[str, Any]] = []
        self._groups: dict[str, dict[str, str]] = {}

    # -- transport ---------------------------------------------------------

    def _require_config(self) -> None:
        if not self.base or not self.token:
            raise ProfassistError(
                503,
                "Moodle is not configured. Add a connection for this workspace, or set "
                "MOODLE_BASE_URL and MOODLE_WS_TOKEN, or leave MOODLE_MODE=fake for tests.",
            )

    @staticmethod
    def _timeout() -> Any:
        import httpx

        return httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        import httpx

        last_error: ProfassistError | None = None
        for attempt in range(2):
            try:
                response = httpx.request(
                    method,
                    url,
                    timeout=self._timeout(),
                    follow_redirects=True,
                    **kwargs,
                )
            except httpx.HTTPError as exc:
                # httpx embeds the full URL, including wstoken, in its message.
                last_error = ProfassistError(503, _redact(f"Moodle could not be reached: {exc}"))
                break
            if response.status_code in _RETRY_STATUS and attempt == 0:
                time.sleep(0.2)
                continue
            if response.status_code >= 400:
                raise ProfassistError(
                    503,
                    f"Moodle returned HTTP {response.status_code} for {url.split('?')[0]}.",
                )
            return response
        if last_error is not None:
            raise last_error
        raise ProfassistError(503, "Moodle did not answer.")

    def _collect_warnings(self, warnings: Any) -> None:
        for warning in warnings or []:
            if not isinstance(warning, dict):
                continue
            self.warnings.append(
                {
                    "item": warning.get("item") or "",
                    "warningcode": warning.get("warningcode") or "",
                    "message": _redact(warning.get("message") or ""),
                }
            )

    def _decode(self, response: Any, function: str) -> Any:
        try:
            payload = response.json()
        except ValueError:
            raise ProfassistError(
                503, f"Moodle returned a non-JSON reply for {function}."
            ) from None
        if isinstance(payload, dict):
            self._collect_warnings(payload.get("warnings"))
            if payload.get("exception") or payload.get("errorcode"):
                raise _moodle_error(function, payload)
        return payload

    def _ws(self, function: str, params: dict[str, Any]) -> Any:
        self._require_config()
        url = f"{self.base}/webservice/rest/server.php"
        query: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        return self._decode(self._request("GET", url, params=query), function)

    def _ws_post(self, function: str, params: dict[str, Any]) -> Any:
        self._require_config()
        url = f"{self.base}/webservice/rest/server.php"
        body: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        return self._decode(self._request("POST", url, data=body), function)

    # -- reads -------------------------------------------------------------

    def site_info(self) -> dict[str, Any]:
        payload = self._ws("core_webservice_get_site_info", {})
        if not isinstance(payload, dict):
            raise ProfassistError(503, "Moodle site info was not an object.")
        functions = [
            str(item.get("name"))
            for item in payload.get("functions") or []
            if isinstance(item, dict) and item.get("name")
        ]
        return {
            "site_url": payload.get("siteurl") or "",
            "site_name": payload.get("sitename") or "",
            "release": payload.get("release") or "",
            "version": str(payload.get("version") or ""),
            "siteid": str(payload.get("siteid") or ""),
            "userid": str(payload.get("userid") or ""),
            "username": payload.get("username") or "",
            "capabilities": {
                "functions": functions,
                "downloadfiles": bool(payload.get("downloadfiles")),
                "uploadfiles": bool(payload.get("uploadfiles")),
                "enablecompletion": bool(payload.get("enablecompletion")),
            },
            "warnings": list(self.warnings),
        }

    def _scope_values(self) -> tuple[str, list[str]]:
        scope = self.course_scope or {}
        mode = str(scope.get("mode") or "all")
        if mode == "idnumbers":
            values = [
                str(item).strip() for item in scope.get("idnumbers") or [] if str(item).strip()
            ]
            return ("idnumber", values) if values else ("", [])
        if mode == "shortnames":
            values = [
                str(item).strip() for item in scope.get("shortnames") or [] if str(item).strip()
            ]
            return ("shortname", values) if values else ("", [])
        return ("", [])

    def list_courses(self) -> list[dict[str, Any]]:
        field, values = self._scope_values()
        rows: list[dict[str, Any]] = []
        if field:
            for value in values:
                payload = self._ws(
                    "core_course_get_courses_by_field",
                    {"field": field, "value": value},
                )
                if isinstance(payload, dict):
                    rows.extend(
                        item for item in payload.get("courses") or [] if isinstance(item, dict)
                    )
        else:
            payload = self._ws("core_course_get_courses", {})
            if isinstance(payload, list):
                rows = [item for item in payload if isinstance(item, dict)]
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            course_id = str(row.get("id") or "")
            if not course_id or course_id in seen:
                continue
            # core_course_get_courses includes the front page; it is not a course.
            if course_id == "1" or str(row.get("format") or "") == "site":
                continue
            if row.get("visible") in (0, False):
                continue
            seen.add(course_id)
            code = (field and row.get(field)) or row.get("idnumber") or row.get("shortname")
            found.append(
                {
                    "id": course_id,
                    "code": str(code or course_id)[:32],
                    "title": row.get("fullname") or row.get("shortname") or course_id,
                    "term": "",
                }
            )
        return found

    def list_students(self, course_external_id: str) -> list[dict[str, Any]]:
        payload = self._ws(
            "core_enrol_get_enrolled_users",
            {
                "courseid": course_external_id,
                "options[0][name]": "withcapability",
                "options[0][value]": "mod/assign:submit",
                "onlyactive": 1,
            },
        )
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            self._collect_warnings(payload.get("warnings"))
            rows = payload.get("users") or []
        else:
            rows = []
        found: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("warningcode"):
                if isinstance(row, dict):
                    self._collect_warnings([row])
                continue
            found.append(
                {
                    "id": str(row.get("id")),
                    "course_id": course_external_id,
                    "display_name": row.get("fullname") or row.get("username") or "",
                    "email": row.get("email") or "",
                    "student_number": str(row.get("idnumber") or ""),
                }
            )
        return found

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
                    raw_levels = criterion.get("levels") or []
                    levels: dict[str, str] = {}
                    details: list[dict[str, Any]] = []
                    max_score = 0.0
                    for index, level in enumerate(raw_levels):
                        key = (
                            _LEVEL_LABELS[index]
                            if index < len(_LEVEL_LABELS)
                            else f"level {index + 1}"
                        )
                        levels[key] = level.get("definition") or level.get("description") or ""
                        max_score = max(max_score, _as_float(level.get("score")))
                        details.append(
                            {
                                "levelid": level.get("id"),
                                "score": level.get("score"),
                                "definition": level.get("definition") or "",
                            }
                        )
                    criteria.append(
                        {
                            "name": criterion.get("description") or f"Criterion {ordinal}",
                            "weight": 1,
                            "criterionid": criterion.get("id"),
                            "levels": levels,
                            "level_details": details,
                            "max_level": max_score,
                        }
                    )
        return criteria

    def _group_names(self, course_external_id: str) -> dict[str, str]:
        if not course_external_id:
            return {}
        cached = self._groups.get(course_external_id)
        if cached is not None:
            return cached
        try:
            payload = self._ws("core_group_get_course_groups", {"courseid": course_external_id})
        except ProfassistError:
            self._groups[course_external_id] = {}
            return {}
        names = {
            str(row.get("id")): str(row.get("name") or "")
            for row in payload or []
            if isinstance(row, dict) and row.get("id")
        }
        self._groups[course_external_id] = names
        return names

    def list_submissions(
        self, assignment_external_id: str, course_external_id: str | None = None
    ) -> list[dict[str, Any]]:
        payload = self._ws(
            "mod_assign_get_submissions",
            {"assignmentids[0]": assignment_external_id, "status": "submitted"},
        )
        group_names = self._group_names(course_external_id or "")
        found: list[dict[str, Any]] = []
        assignments = payload.get("assignments", []) if isinstance(payload, dict) else []
        for assignment in assignments:
            for submission in assignment.get("submissions", []) or []:
                if not isinstance(submission, dict):
                    continue
                if str(submission.get("status") or "submitted") != "submitted":
                    continue
                # Moodle can return earlier attempts; only the latest is graded.
                if int(submission.get("latest") or 0) <= 0:
                    continue
                text = ""
                for plugin in submission.get("plugins", []) or []:
                    for field in plugin.get("editorfields", []) or []:
                        text += field.get("text") or ""
                author = str(submission.get("userid") or "")
                group_id = str(submission.get("groupid") or "")
                found.append(
                    {
                        "id": str(submission.get("id")),
                        "assignment_id": assignment_external_id,
                        "group_name": group_names.get(group_id) or f"User {author}",
                        "author_id": author,
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

    def list_activity(self, course_external_id: str) -> list[dict[str, Any]]:
        """Pull the day-35 snapshot from ``local_profassist_get_activity``.

        The function ships with the bundled demo simulator and is not part of a
        stock Moodle. Only the 14 allowlisted columns are kept; a missing column
        stays ``None`` so it is a data gap, not a zero.
        """
        from app.profassist.ml.dropout import FEATURE_COLUMNS

        payload = self._ws("local_profassist_get_activity", {"courseid": course_external_id})
        rows = (payload.get("students") or []) if isinstance(payload, dict) else []
        found: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            userid = str(row.get("userid") or "")
            features = row.get("features")
            if not userid or not isinstance(features, dict):
                continue
            found.append(
                {
                    "userid": userid,
                    "features": {column: features.get(column) for column in FEATURE_COLUMNS},
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
        self._require_config()
        url = fileurl
        if "token=" not in url and "wstoken=" not in url:
            join = "&" if "?" in url else "?"
            url = f"{url}{join}token={self.token}"
        return self._request("GET", url).content

    def lti_launch(self, claims: dict[str, Any]) -> dict[str, Any]:
        parsed = parse_lti_launch(claims)
        parsed["mode"] = self.mode
        if not parsed["course_external_id"]:
            raise ProfassistError(400, "LTI launch is missing the context id claim.")
        return parsed

    def push(self, item: dict[str, Any]) -> dict[str, Any]:
        allowed = self.push_enabled if self.source == "org" else moodle_push_enabled()
        if not allowed:
            raise ProfassistError(
                501,
                "Real grade push is off. Turn on push for this workspace, or set "
                "MOODLE_PUSH_ENABLED=true only after the service account has "
                "mod/assign:grade. Until then the push is refused.",
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


def get_connector(spec: MoodleConnectionSpec | None = None) -> MoodleConnector:
    if moodle_mode() == "real":
        return RealMoodleConnector(spec)
    return FakeMoodleConnector()
