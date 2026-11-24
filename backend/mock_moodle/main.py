"""A local Moodle Web Services endpoint for the docker demo.

The simulator implements the functions the ProfAssist connector calls, plus the
create/update functions a demo needs. It speaks the same JSON shape as Moodle:
errors are a 200 response with ``exception``/``errorcode``, and list functions
return a bare list. Create/update functions return a wrapper with the ids they
touched and an empty ``warnings`` list (a real Moodle returns a bare array; the
ids are the useful part for a demo).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request

from . import data as store

app = FastAPI(title="ProfAssist Moodle WS simulator", version="1.0.0")


# -- helpers ---------------------------------------------------------------


def _rows(params: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    """Read Moodle's ``prefix[0][field]`` form parameters into rows."""
    rows: dict[int, dict[str, Any]] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\[(\d+)\]\[([A-Za-z_]+)\]$")
    for key, value in params.items():
        match = pattern.match(str(key))
        if match:
            rows.setdefault(int(match.group(1)), {})[match.group(2)] = value
    return [rows[index] for index in sorted(rows)]


def _indexed(params: dict[str, Any], name: str) -> list[str]:
    """Read ``name[0]``, ``name[1]`` ... parameters in order."""
    found: dict[int, str] = {}
    pattern = re.compile(rf"^{re.escape(name)}\[(\d+)\]$")
    for key, value in params.items():
        match = pattern.match(str(key))
        if match:
            found[int(match.group(1))] = str(value)
    return [found[index] for index in sorted(found)]


def _warning(item: str, code: str, message: str, itemid: int = 0) -> dict[str, Any]:
    return {
        "item": item,
        "itemid": itemid,
        "warningcode": code,
        "message": message,
    }


def _error(exception: str, code: str, message: str) -> dict[str, Any]:
    return {
        "exception": exception,
        "errorcode": code,
        "message": message,
        "debuginfo": message,
    }


def _find_course(field: str, value: Any) -> dict[str, Any] | None:
    if field == "id":
        try:
            found = store.COURSES.get(int(value))
        except (TypeError, ValueError):
            return None
        return dict(found) if found else None
    if field in {"idnumber", "shortname"}:
        for course in store.COURSES.values():
            if str(course.get(field) or "") == str(value):
                return dict(course)
    return None


# -- web-service functions -------------------------------------------------


def site_info(params: dict[str, Any]) -> dict[str, Any]:
    del params
    return {
        "sitename": store.SITE["sitename"],
        "username": store.SITE["username"],
        "firstname": store.SITE["firstname"],
        "lastname": store.SITE["lastname"],
        "fullname": f"{store.SITE['firstname']} {store.SITE['lastname']}",
        "lang": "en",
        "userid": store.SITE["userid"],
        "siteurl": store.SITE["siteurl"],
        "userpictureurl": "",
        "functions": [
            {"name": name, "version": store.SITE["version"]} for name in sorted(FUNCTIONS)
        ],
        "downloadfiles": 1,
        "uploadfiles": 1,
        "release": store.SITE["release"],
        "version": store.SITE["version"],
        "siteid": store.SITE["siteid"],
        "enablecompletion": 1,
        "warnings": [],
    }


def get_courses(params: dict[str, Any]) -> list[dict[str, Any]]:
    del params
    rows = [dict(store.FRONT_PAGE), *[dict(item) for item in store.COURSES.values()]]
    return sorted(rows, key=lambda row: int(row["id"]))


def get_courses_by_field(params: dict[str, Any]) -> dict[str, Any]:
    field = str(params.get("field") or "")
    value = params.get("value")
    if field not in {"id", "idnumber", "shortname"}:
        return {
            "courses": [],
            "warnings": [_warning("field", "invalidfield", f"Unsupported course field {field!r}.")],
        }
    if field == "id" and str(value) == "1":
        return {"courses": [dict(store.FRONT_PAGE)], "warnings": []}
    found = _find_course(field, value)
    return {"courses": [found] if found else [], "warnings": []}


def create_courses(params: dict[str, Any]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for row in _rows(params, "courses"):
        shortname = str(row.get("shortname") or row.get("idnumber") or "").strip()
        fullname = str(row.get("fullname") or shortname).strip()
        if not shortname or not fullname:
            warnings.append(
                _warning("courses", "missingfield", "A course needs a shortname and a fullname.")
            )
            continue
        if any(str(item.get("shortname")) == shortname for item in store.COURSES.values()):
            warnings.append(
                _warning("shortname", "shortnametaken", f"Shortname {shortname} is already used.")
            )
            continue
        courseid = store.next_course_id()
        store.COURSES[courseid] = {
            "id": courseid,
            "shortname": shortname,
            "fullname": fullname,
            "displayname": str(row.get("displayname") or fullname),
            "categoryid": int(row.get("categoryid") or 1),
            "categoryname": str(row.get("categoryname") or "Demo"),
            "summary": str(row.get("summary") or ""),
            "summaryformat": 1,
            "format": str(row.get("format") or "topics"),
            "showgrades": 1,
            "newsitems": 0,
            "startdate": int(row.get("startdate") or 1767225600),
            "enddate": int(row.get("enddate") or 1798761600),
            "visible": int(row.get("visible", 1)),
            "idnumber": str(row.get("idnumber") or shortname),
            "numsections": int(row.get("numsections") or 0),
        }
        store.ENROLMENTS[courseid] = set()
        created.append(
            {
                "id": courseid,
                "shortname": shortname,
                "fullname": fullname,
                "idnumber": store.COURSES[courseid]["idnumber"],
            }
        )
    if not created and not warnings:
        warnings.append(_warning("courses", "missingfield", "No courses were supplied."))
    return {"courses": created, "warnings": warnings}


def update_courses(params: dict[str, Any]) -> dict[str, Any]:
    updated: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    numeric = {"categoryid", "startdate", "enddate", "visible", "numsections"}
    fields = {
        "shortname",
        "fullname",
        "displayname",
        "categoryid",
        "summary",
        "format",
        "startdate",
        "enddate",
        "visible",
        "idnumber",
        "numsections",
    }
    for row in _rows(params, "courses"):
        try:
            courseid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            courseid = 0
        course = store.COURSES.get(courseid)
        if course is None:
            warnings.append(
                _warning("courses", "notfound", f"Course {courseid} was not found.", courseid)
            )
            continue
        for key in fields:
            if key not in row:
                continue
            course[key] = int(row[key]) if key in numeric else str(row[key])
        updated.append(
            {"id": courseid, "shortname": course["shortname"], "fullname": course["fullname"]}
        )
    return {"courses": updated, "warnings": warnings}


def enrolled_users(params: dict[str, Any]) -> Any:
    try:
        courseid = int(params.get("courseid") or 0)
    except (TypeError, ValueError):
        courseid = 0
    if courseid not in store.COURSES:
        return {
            "users": [],
            "warnings": [_warning("courseid", "notfound", f"Course {courseid} was not found.")],
        }
    return [store.user_view(userid) for userid in sorted(store.ENROLMENTS.get(courseid, set()))]


def create_users(params: dict[str, Any]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for row in _rows(params, "users"):
        username = str(row.get("username") or "").strip().lower()
        email = str(row.get("email") or "").strip()
        if not username:
            username = email.split("@")[0].strip().lower() or f"user{store.next_user_id()}"
        if any(item.get("username") == username for item in store.USERS.values()):
            warnings.append(
                _warning("username", "usernametaken", f"Username {username} is already used.")
            )
            continue
        userid = store.next_user_id()
        firstname = str(row.get("firstname") or username.split(".")[0].title())
        lastname = str(row.get("lastname") or username.split(".")[-1].title())
        store.USERS[userid] = {
            "id": userid,
            "username": username,
            "firstname": firstname,
            "lastname": lastname,
            "fullname": f"{firstname} {lastname}",
            "email": email or f"{username}@demo.invalid",
            "idnumber": str(row.get("idnumber") or userid),
            "department": str(row.get("department") or ""),
            "institution": str(row.get("institution") or "ProfAssist Demo University"),
            "city": str(row.get("city") or ""),
            "country": str(row.get("country") or ""),
            "auth": "manual",
            "confirmed": True,
            "suspended": False,
            "lang": str(row.get("lang") or "en"),
            "timezone": str(row.get("timezone") or "UTC"),
            "firstaccess": 0,
            "lastaccess": 0,
            "description": str(row.get("description") or ""),
            "roles": [{"roleid": 5, "name": "Student", "shortname": "student", "sortorder": 0}],
        }
        created.append({"id": userid, "username": username})
    if not created and not warnings:
        warnings.append(_warning("users", "missingfield", "No users were supplied."))
    return {"users": created, "warnings": warnings}


def update_users(params: dict[str, Any]) -> dict[str, Any]:
    updated: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fields = {
        "username",
        "firstname",
        "lastname",
        "email",
        "idnumber",
        "department",
        "institution",
        "city",
        "country",
        "description",
        "lang",
        "timezone",
    }
    for row in _rows(params, "users"):
        try:
            userid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            userid = 0
        user = store.USERS.get(userid)
        if user is None:
            warnings.append(_warning("users", "notfound", f"User {userid} was not found.", userid))
            continue
        for key in fields:
            if key in row:
                user[key] = str(row[key])
        user["fullname"] = f"{user['firstname']} {user['lastname']}"
        updated.append({"id": userid, "username": user["username"]})
    return {"users": updated, "warnings": warnings}


def get_assignments(params: dict[str, Any]) -> dict[str, Any]:
    courseids = _indexed(params, "courseids")
    courses: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for raw in courseids or [str(courseid) for courseid in store.COURSES]:
        try:
            courseid = int(raw)
        except (TypeError, ValueError):
            warnings.append(_warning("courseids", "invalidcourseid", f"Bad course id {raw!r}."))
            continue
        course = store.COURSES.get(courseid)
        if course is None:
            warnings.append(
                _warning("courseids", "notfound", f"Course {courseid} was not found.", courseid)
            )
            continue
        assignments = [
            dict(item) for item in store.ASSIGNMENTS.values() if int(item["course"]) == courseid
        ]
        courses.append(
            {
                "id": courseid,
                "fullname": course["fullname"],
                "shortname": course["shortname"],
                "category": course.get("categoryid", 1),
                "assignments": assignments,
            }
        )
    return {"courses": courses, "warnings": warnings}


def get_submissions(params: dict[str, Any]) -> dict[str, Any]:
    assignmentids = _indexed(params, "assignmentids")
    wanted = str(params.get("status") or "")
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for raw in assignmentids or [str(item) for item in store.ASSIGNMENTS]:
        try:
            assignmentid = int(raw)
        except (TypeError, ValueError):
            warnings.append(
                _warning("assignmentids", "invalidassignmentid", f"Bad assignment id {raw!r}.")
            )
            continue
        if assignmentid not in store.ASSIGNMENTS:
            warnings.append(
                _warning(
                    "assignmentids",
                    "notfound",
                    f"Assignment {assignmentid} was not found.",
                    assignmentid,
                )
            )
            continue
        submissions = []
        for submission in store.SUBMISSIONS.values():
            if int(submission["assignment"]) != assignmentid:
                continue
            if wanted and str(submission["status"]) != wanted:
                continue
            submissions.append(
                {
                    "id": submission["id"],
                    "userid": submission["userid"],
                    "attemptnumber": submission["attemptnumber"],
                    "timecreated": submission["timecreated"],
                    "timemodified": submission["timemodified"],
                    "status": submission["status"],
                    "groupid": submission["groupid"],
                    "assignment": submission["assignment"],
                    "latest": submission["latest"],
                    "plugins": [
                        {
                            "type": "onlinetext",
                            "name": "Online text",
                            "subtype": "",
                            "editorfields": [
                                {
                                    "name": "text",
                                    "description": "Online text",
                                    "text": submission["text"],
                                    "format": 1,
                                }
                            ],
                        },
                        {
                            "type": "file",
                            "name": "File submissions",
                            "subtype": "",
                            "fileareas": [{"area": "submission_files", "files": []}],
                        },
                    ],
                }
            )
        rows.append({"assignmentid": assignmentid, "submissions": submissions})
    return {"assignments": rows, "warnings": warnings}


def get_grading_definitions(params: dict[str, Any]) -> dict[str, Any]:
    cmids = _indexed(params, "cmids")
    areas: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for raw in cmids:
        try:
            cmid = int(raw)
        except (TypeError, ValueError):
            warnings.append(_warning("cmids", "invalidcmid", f"Bad course-module id {raw!r}."))
            continue
        rubric = store.RUBRICS.get(cmid)
        if rubric is None:
            warnings.append(
                _warning("cmids", "notfound", f"No active rubric for cmid {cmid}.", cmid)
            )
            continue
        areas.append(
            {
                "cmid": cmid,
                "contextid": 1,
                "component": "mod_assign",
                "areaname": "submissions",
                "activemethod": "rubric",
                "definitions": [dict(rubric)],
            }
        )
    return {"areas": areas, "warnings": warnings}


def save_grade(params: dict[str, Any]) -> dict[str, Any]:
    try:
        assignmentid = int(params.get("assignmentid") or 0)
        userid = int(params.get("userid") or 0)
        grade = float(params.get("grade") or 0)
    except (TypeError, ValueError):
        return {
            "warnings": [
                _warning(
                    "grade", "invalidparameter", "assignmentid, userid, and grade are required."
                )
            ]
        }
    if assignmentid not in store.ASSIGNMENTS or userid not in store.USERS:
        return {
            "warnings": [
                _warning("grade", "notfound", "Assignment or user was not found.", assignmentid)
            ]
        }
    feedback = str(params.get("plugindata[assignfeedbackcomments_editor][text]") or "")
    store.GRADES[(assignmentid, userid)] = {"grade": grade, "feedback": feedback}
    return {
        "warnings": [],
        "assignmentid": assignmentid,
        "userid": userid,
        "savedgrade": grade,
        "attemptnumber": int(params.get("attemptnumber") or -1),
    }


def get_course_groups(params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        courseid = int(params.get("courseid") or 0)
    except (TypeError, ValueError):
        courseid = 0
    return [dict(group) for group in store.GROUPS.values() if int(group["courseid"]) == courseid]


def get_group_members(params: dict[str, Any]) -> list[dict[str, Any]]:
    groupids = _indexed(params, "groupids")
    try:
        courseid = int(params.get("courseid") or 0)
    except (TypeError, ValueError):
        courseid = 0
    targets = [int(raw) for raw in groupids if str(raw).isdigit()]
    if not targets:
        targets = [
            int(groupid)
            for groupid, group in store.GROUPS.items()
            if not courseid or int(group["courseid"]) == courseid
        ]
    rows = []
    for groupid in targets:
        group = store.GROUPS.get(groupid)
        if group is None:
            continue
        rows.append(
            {
                "groupid": groupid,
                "name": group["name"],
                "description": group["description"],
                "members": [
                    store.user_view(userid) for userid in store.GROUP_MEMBERS.get(groupid, [])
                ],
            }
        )
    return rows


def course_user_profiles(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _rows(params, "userlist"):
        try:
            userid = int(item.get("userid") or 0)
            courseid = int(item.get("courseid") or 0)
        except (TypeError, ValueError):
            continue
        user = store.USERS.get(userid)
        course = store.COURSES.get(courseid)
        if user is None or course is None:
            continue
        rows.append(
            {
                "userid": userid,
                "courseid": courseid,
                "course": course["fullname"],
                "fullname": user["fullname"],
                "email": user["email"],
                "idnumber": user["idnumber"],
                "username": user["username"],
                "roles": list(user["roles"]),
            }
        )
    return rows


def get_activity(params: dict[str, Any]) -> dict[str, Any]:
    try:
        courseid = int(params.get("courseid") or 0)
    except (TypeError, ValueError):
        courseid = 0
    if courseid not in store.COURSES:
        return {
            "students": [],
            "warnings": [_warning("courseid", "notfound", f"Course {courseid} was not found.")],
        }
    students = [
        {"userid": userid, "features": dict(store.ACTIVITY[userid])}
        for userid in sorted(store.ENROLMENTS.get(courseid, set()))
        if userid in store.ACTIVITY
    ]
    warnings = []
    if not students:
        warnings.append(
            _warning(
                "activity",
                "noactivity",
                "This demo exposes local_profassist_get_activity but has no rows for this course.",
                courseid,
            )
        )
    return {"students": students, "warnings": warnings}


def get_workshops(params: dict[str, Any]) -> dict[str, Any]:
    del params
    return {"workshops": [], "warnings": []}


def enrol_users(params: dict[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    for row in _rows(params, "enrolments"):
        try:
            courseid = int(row.get("courseid") or 0)
            userid = int(row.get("userid") or 0)
        except (TypeError, ValueError):
            warnings.append(
                _warning("enrolments", "invalidparameter", "A course and user are required.")
            )
            continue
        if courseid not in store.COURSES or userid not in store.USERS:
            warnings.append(
                _warning("enrolments", "notfound", "Course or user was not found.", courseid)
            )
            continue
        store.ENROLMENTS.setdefault(courseid, set()).add(userid)
    return {"warnings": warnings}


def add_group_members(params: dict[str, Any]) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    for row in _rows(params, "members"):
        try:
            groupid = int(row.get("groupid") or 0)
            userid = int(row.get("userid") or 0)
        except (TypeError, ValueError):
            warnings.append(
                _warning("members", "invalidparameter", "A group and user are required.")
            )
            continue
        if groupid not in store.GROUPS or userid not in store.USERS:
            warnings.append(
                _warning("members", "notfound", "Group or user was not found.", groupid)
            )
            continue
        members = store.GROUP_MEMBERS.setdefault(groupid, [])
        if userid not in members:
            members.append(userid)
    return {"warnings": warnings}


FUNCTIONS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "core_webservice_get_site_info": site_info,
    "core_course_get_courses": get_courses,
    "core_course_get_courses_by_field": get_courses_by_field,
    "core_course_create_courses": create_courses,
    "core_course_update_courses": update_courses,
    "core_enrol_get_enrolled_users": enrolled_users,
    "core_user_create_users": create_users,
    "core_user_update_users": update_users,
    "mod_assign_get_assignments": get_assignments,
    "mod_assign_get_submissions": get_submissions,
    "core_grading_get_definitions": get_grading_definitions,
    "mod_assign_save_grade": save_grade,
    "core_group_get_course_groups": get_course_groups,
    "core_group_get_group_members": get_group_members,
    "core_user_get_course_user_profiles": course_user_profiles,
    "local_profassist_get_activity": get_activity,
    "mod_workshop_get_workshops_by_courses": get_workshops,
    "enrol_manual_enrol_users": enrol_users,
    "core_group_add_group_members": add_group_members,
}


def dispatch(function: str, params: dict[str, Any]) -> Any:
    """Run one function without the HTTP layer. Tests and demos use this."""
    handler = FUNCTIONS.get(function)
    if handler is None:
        return _error(
            "webservice_access_exception",
            "invalidfunction",
            f"Invalid function name: {function}",
        )
    return handler(params)


async def _params(request: Request) -> dict[str, Any]:
    if request.method == "POST":
        form = await request.form()
        return {str(key): value for key, value in form.items()}
    return {str(key): value for key, value in request.query_params.items()}


# -- routes ----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "moodle-mock",
        "courses": len(store.COURSES),
        "users": len(store.USERS),
    }


@app.api_route("/webservice/rest/server.php", methods=["GET", "POST"])
async def webservice(request: Request) -> Any:
    params = await _params(request)
    token = str(params.get("wstoken") or "")
    function = str(params.get("wsfunction") or "")
    if token != store.TOKEN:
        return _error(
            "webservice_access_exception",
            "invalidtoken",
            "Invalid token - token not found",
        )
    return dispatch(function, params)
