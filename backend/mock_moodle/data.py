"""Seeded, fictional data for the local Moodle web-service simulator.

The ids are stable so a demo can be replayed: course 903, users 1001-1012,
groups A-F, assignments 901/902, and submissions 801-806. ``reset()`` restores
the seed after a mutating call or a test.
"""

from __future__ import annotations

from typing import Any

TOKEN = "demo-token"

SITE: dict[str, Any] = {
    "sitename": "ProfAssist Demo Moodle",
    "siteurl": "http://moodle-mock:8090",
    "release": "4.5 (Build: 20241007)",
    "version": "2024100700",
    "siteid": 1,
    "username": "wsuser",
    "firstname": "Web",
    "lastname": "Service",
    "userid": 2,
}

FRONT_PAGE: dict[str, Any] = {}

COURSES: dict[int, dict[str, Any]] = {}
USERS: dict[int, dict[str, Any]] = {}
GROUPS: dict[int, dict[str, Any]] = {}
GROUP_MEMBERS: dict[int, list[int]] = {}
ENROLMENTS: dict[int, set[int]] = {}
ASSIGNMENTS: dict[int, dict[str, Any]] = {}
SUBMISSIONS: dict[int, dict[str, Any]] = {}
RUBRICS: dict[int, dict[str, Any]] = {}
ACTIVITY: dict[int, dict[str, Any]] = {}
GRADES: dict[tuple[int, int], dict[str, Any]] = {}

# A/B share the method, C/D share the findings, and E/F share the introduction.
_SHARED_METHOD = (
    "We counted the east entrance in ten-minute blocks across four teaching days "
    "and logged each reading in the shared notebook. Facilities gave us the meter "
    "export for the same week, so the comparison used the same dates and the same "
    "building. Where the two records disagreed we kept the lower figure and wrote "
    "down why. The method is repeatable because the blocks and the rooms did not "
    "change between visits."
)
_SHARED_FINDINGS = (
    "The queue at the print desk peaked between eleven and noon, when two classes "
    "released at the same time. On the two days we sampled, the wait never fell "
    "below nine minutes during that hour and cleared within four minutes once one "
    "class had gone. The pattern points at timetable overlap rather than a shortage "
    "of printers. We would repeat the count on a third day before recommending a "
    "rota change."
)
_SHARED_INTRODUCTION = (
    "This report examines how often a booked workshop room stood empty during the "
    "first three weeks of term. We chose the question because the booking system "
    "and the room log disagree, and because an empty room costs the same as a full "
    "one. Our evidence comes from two floors and one timetable, so the finding is "
    "local and should not be read as a campus-wide average. The rest of the report "
    "explains the count and the limits."
)

_SUBMISSION_TEXT = {
    801: (
        "Introduction\n"
        "Our group measured how quickly the east entrance clears after a lecture ends. "
        "We picked that door because the timetable sends two large classes through it at "
        "the same time. The question is narrow on purpose: a door count is easier to "
        "defend than a claim about the whole building.\n\n"
        "Method\n"
        f"{_SHARED_METHOD}\n\n"
        "Findings\n"
        "The door cleared within six minutes on three of the four days. The fourth day "
        "was slower because a fire drill closed the west route. We would not change the "
        "timetable on one slow day, and the group is still drafting the recommendation."
    ),
    802: (
        "Introduction\n"
        "We looked at how students leave the main teaching block after the afternoon "
        "lecture. The brief asked for an operational problem, and a crowded doorway is "
        "one that facilities can act on without new equipment.\n\n"
        "Method\n"
        f"{_SHARED_METHOD}\n\n"
        "Findings\n"
        "The east entrance is the busiest exit for about ten minutes after the lecture. "
        "Our count was lower than the facilities estimate, which may mean some students "
        "used the stair by the library. We are reporting the lower figure and explaining "
        "the difference rather than smoothing it away."
    ),
    803: (
        "Introduction\n"
        "This report looks at the print desk in the student hub. We chose it because "
        "students mention the queue often, but nobody had timed it for a full week.\n\n"
        "Method\n"
        "One member of the group timed the queue at the start of each hour and another "
        "recorded the number of printers in use. We did not count the same person twice "
        "and we left when the desk closed early.\n\n"
        "Findings\n"
        f"{_SHARED_FINDINGS}"
    ),
    804: (
        "Introduction\n"
        "The group studied waiting time at the hub print desk during the busiest teaching "
        "week of the term. The aim was to separate a staffing problem from a timing "
        "problem before asking for a change.\n\n"
        "Method\n"
        "We sampled two hours a day and wrote down the queue length every ten minutes. "
        "The sheet names the hour, not the student, so the record contains no personal "
        "data. A second observer checked the counts on the busiest day.\n\n"
        "Findings\n"
        f"{_SHARED_FINDINGS}"
    ),
    805: (
        "Introduction\n"
        f"{_SHARED_INTRODUCTION}\n\n"
        "Method\n"
        "We compared the room booking export with a short walk past the same rooms at the "
        "start of each workshop. A room counted as empty only when it stayed empty five "
        "minutes after the booked start. The walk took the same route every week so the "
        "comparison stayed fair.\n\n"
        "Findings\n"
        "Two rooms were empty on three of the four visits. Both were booked by the same "
        "module, which suggests a timetable error rather than disinterest. We recommend "
        "checking that module's room request before changing the booking rules."
    ),
    806: (
        "Introduction\n"
        f"{_SHARED_INTRODUCTION}\n\n"
        "Method\n"
        "The group split the building by floor and checked each booked room once. We "
        "avoided a room when a class was clearly using it and recorded the booking code "
        "from the door screen. The log was typed up the same afternoon so the notes "
        "stayed close to what we saw.\n\n"
        "Findings\n"
        "Empty rooms clustered on the lower floor, where the booking screen is hard to "
        "read from the corridor. That is a small usability finding, not proof that the "
        "timetable is wrong. A follow-up with the timetabling office would settle it."
    ),
}

# The 12 seeded day-35 rows. They produce 5 review and 7 routine bands with the
# shipped dropout bundle (threshold 0.1). The values are fictional.
_ACTIVITY_ROWS: dict[int, list[float]] = {
    1001: [0, 9, 0, 11, 0, 0, 2, 2, 0, 0.0, 2, -9, 28.0, 0.0],
    1002: [1, 10, 2, 15, 1, 0, 1, 2, 0, 0.0, 2, -9, 20.0, 0.0],
    1003: [2, 8, 3, 10, 2, 0, 1, 2, 1, 42.0, 1, -6, 9.0, 0.0],
    1004: [1, 12, 1, 13, 0, 0, 2, 2, 0, 0.0, 2, -11, 21.0, 0.0],
    1005: [3, 7, 4, 9, 2, 0, 1, 2, 1, 51.0, 1, -4, 6.0, 0.0],
    1006: [14, 6, 25, 8, 2, 1, 0, 2, 2, 82.0, 0, 8, 0.0, 0.0],
    1007: [13, 6, 22, 7, 1, 0, 0, 2, 2, 76.0, 0, 7, 0.0, 0.0],
    1008: [14, 7, 28, 9, 2, 1, 0, 2, 2, 90.0, 0, 7, 0.0, 0.0],
    1009: [13, 9, 20, 12, 3, 2, 0, 2, 2, 79.0, 0, 4, 1.0, 0.0],
    1010: [13, 7, 23, 8, 1, 1, 0, 2, 2, 88.0, 0, 6, 0.0, 0.0],
    1011: [12, 7, 17, 10, 2, 1, 0, 2, 2, 75.0, 0, 5, 2.0, 0.0],
    1012: [10, 7, 14, 10, 2, 1, 0, 2, 2, 74.0, 0, 3, 3.0, 0.0],
}

_FEATURE_COLUMNS = (
    "active_days_14d",
    "active_days_previous_14d",
    "interactions_14d",
    "interactions_previous_14d",
    "resource_views_14d",
    "forum_posts_14d",
    "late_submissions_to_date",
    "assignments_due_to_date",
    "scores_available_count",
    "mean_score_pct_to_date",
    "missed_assignments",
    "activity_change",
    "days_since_last_activity",
    "no_activity_history",
)

_NAMES = {
    1001: ("Sara", "Al Maktoum"),
    1002: ("Omar", "Haddad"),
    1003: ("Noor", "Rahman"),
    1004: ("Layla", "Karim"),
    1005: ("Hana", "Yusuf"),
    1006: ("Adam", "Cole"),
    1007: ("Priya", "Nair"),
    1008: ("Jonah", "Ellis"),
    1009: ("Mina", "Farouk"),
    1010: ("Chris", "Adeyemi"),
    1011: ("Lina", "Haddad"),
    1012: ("Samir", "Qureshi"),
}

_GROUP_NAMES = {1: "Group A", 2: "Group B", 3: "Group C", 4: "Group D", 5: "Group E", 6: "Group F"}

# Submission 801 -> group A, 802 -> B, and so on. The author is the first
# member of the group; the second member stays on the roster.
_SUBMISSION_GROUPS = {801: 1, 802: 2, 803: 3, 804: 4, 805: 5, 806: 6}


def reset() -> None:
    """Restore the seeded demo site. Safe to call between tests."""
    FRONT_PAGE.clear()
    FRONT_PAGE.update(
        {
            "id": 1,
            "shortname": "site",
            "fullname": SITE["sitename"],
            "displayname": SITE["sitename"],
            "categoryid": 0,
            "categoryname": "",
            "summary": "Demo site front page.",
            "summaryformat": 1,
            "format": "site",
            "showgrades": 1,
            "newsitems": 0,
            "startdate": 1767225600,
            "enddate": 1798761600,
            "visible": 1,
            "idnumber": "",
        }
    )
    COURSES.clear()
    COURSES[903] = {
        "id": 903,
        "shortname": "PIPE903",
        "fullname": "Professional Integrity and Practice",
        "displayname": "Professional Integrity and Practice",
        "categoryid": 1,
        "categoryname": "Professional programmes",
        "summary": "A demo course for the ProfAssist Moodle connector.",
        "summaryformat": 1,
        "format": "topics",
        "showgrades": 1,
        "newsitems": 5,
        "startdate": 1767225600,
        "enddate": 1798761600,
        "visible": 1,
        "idnumber": "PIPE903",
        "numsections": 12,
    }
    USERS.clear()
    for userid, (firstname, lastname) in _NAMES.items():
        username = f"{firstname}.{lastname}".lower().replace(" ", "")
        USERS[userid] = {
            "id": userid,
            "username": username,
            "firstname": firstname,
            "lastname": lastname,
            "fullname": f"{firstname} {lastname}",
            "email": f"{username}@student.uowd.ac.ae",
            "idnumber": f"888{userid}",
            "department": "Professional programmes",
            "institution": "ProfAssist Demo University",
            "city": "Dubai",
            "country": "AE",
            "auth": "manual",
            "confirmed": True,
            "suspended": False,
            "lang": "en",
            "timezone": "Asia/Dubai",
            "firstaccess": 1767225600,
            "lastaccess": 1769817600,
            "description": "",
            "roles": [{"roleid": 5, "name": "Student", "shortname": "student", "sortorder": 0}],
        }
    GROUPS.clear()
    GROUP_MEMBERS.clear()
    for index, name in _GROUP_NAMES.items():
        GROUPS[index] = {
            "id": index,
            "courseid": 903,
            "name": name,
            "description": "",
            "descriptionformat": 1,
            "idnumber": chr(64 + index),
            "enrolmentkey": "",
            "visibility": 1,
        }
    member_ids = list(_NAMES)
    for index in range(6):
        GROUP_MEMBERS[index + 1] = [member_ids[index * 2], member_ids[index * 2 + 1]]
    ENROLMENTS.clear()
    ENROLMENTS[903] = set(member_ids)
    ASSIGNMENTS.clear()
    ASSIGNMENTS[901] = {
        "id": 901,
        "cmid": 1901,
        "course": 903,
        "name": "Operations review: group report",
        "intro": "One group report on an operational problem on campus.",
        "introformat": 1,
        "duedate": 1769904000,
        "allowsubmissionsfromdate": 1767225600,
        "cutoffdate": 1770000000,
        "grade": 100,
        "timemodified": 1769817600,
        "teamsubmission": 1,
        "submissiondrafts": 0,
        "sendnotifications": 1,
        "sendlatenotifications": 1,
        "sendstudentnotifications": 1,
        "blindmarking": 0,
        "hidegrader": 0,
        "revealidentities": 0,
        "attemptreopenmethod": "manual",
        "maxattempts": -1,
        "markingworkflow": 0,
        "markingallocation": 0,
        "requiresubmissionstatement": 0,
        "completionsubmit": 0,
        "gradingduedate": 1770000000,
    }
    ASSIGNMENTS[902] = {
        "id": 902,
        "cmid": 1902,
        "course": 903,
        "name": "Reflective memo",
        "intro": "A short individual reflection on the group report.",
        "introformat": 1,
        "duedate": 1771200000,
        "allowsubmissionsfromdate": 1769904000,
        "cutoffdate": 1771200000,
        "grade": 100,
        "timemodified": 1769904000,
        "teamsubmission": 0,
        "submissiondrafts": 0,
        "sendnotifications": 1,
        "sendlatenotifications": 1,
        "sendstudentnotifications": 1,
        "blindmarking": 0,
        "hidegrader": 0,
        "revealidentities": 0,
        "attemptreopenmethod": "manual",
        "maxattempts": -1,
        "markingworkflow": 0,
        "markingallocation": 0,
        "requiresubmissionstatement": 0,
        "completionsubmit": 0,
        "gradingduedate": 1771200000,
    }
    SUBMISSIONS.clear()
    for submission_id, group_index in _SUBMISSION_GROUPS.items():
        author = GROUP_MEMBERS[group_index][0]
        SUBMISSIONS[submission_id] = {
            "id": submission_id,
            "assignment": 901,
            "userid": author,
            "groupid": group_index,
            "attemptnumber": 0,
            "latest": 1,
            "status": "submitted",
            "timecreated": 1769720000 + submission_id,
            "timemodified": 1769720000 + submission_id,
            "text": _SUBMISSION_TEXT[submission_id],
        }
    RUBRICS.clear()
    RUBRICS[1901] = {
        "id": 501,
        "name": "Operations review rubric",
        "rubric": {
            "criteria": [
                {
                    "id": 601,
                    "description": "Evidence and analysis",
                    "levels": [
                        {
                            "id": 7001,
                            "score": 1,
                            "definition": "Thin evidence; the claim is not supported.",
                        },
                        {
                            "id": 7002,
                            "score": 2,
                            "definition": "Some evidence, but the link to the claim is partial.",
                        },
                        {
                            "id": 7003,
                            "score": 3,
                            "definition": "Clear evidence supports the main claim.",
                        },
                        {
                            "id": 7004,
                            "score": 4,
                            "definition": "Strong, specific evidence with a stated limitation.",
                        },
                    ],
                },
                {
                    "id": 602,
                    "description": "Method and repeatability",
                    "levels": [
                        {
                            "id": 7101,
                            "score": 1,
                            "definition": "The method cannot be repeated from the report.",
                        },
                        {
                            "id": 7102,
                            "score": 2,
                            "definition": "The method is named but the steps are incomplete.",
                        },
                        {
                            "id": 7103,
                            "score": 3,
                            "definition": "The steps are clear enough to repeat.",
                        },
                        {
                            "id": 7104,
                            "score": 4,
                            "definition": "The steps are clear and the limits are discussed.",
                        },
                    ],
                },
                {
                    "id": 603,
                    "description": "Recommendation",
                    "levels": [
                        {
                            "id": 7201,
                            "score": 1,
                            "definition": "No recommendation, or it is unrelated to the evidence.",
                        },
                        {
                            "id": 7202,
                            "score": 2,
                            "definition": "A recommendation is present but weakly tied to the evidence.",
                        },
                        {
                            "id": 7203,
                            "score": 3,
                            "definition": "A reasonable recommendation follows from the evidence.",
                        },
                        {
                            "id": 7204,
                            "score": 4,
                            "definition": "The recommendation is specific, bounded, and evidence-led.",
                        },
                    ],
                },
            ]
        },
    }
    ACTIVITY.clear()
    for userid, values in _ACTIVITY_ROWS.items():
        ACTIVITY[userid] = dict(zip(_FEATURE_COLUMNS, values, strict=True))
    GRADES.clear()


def next_course_id() -> int:
    return max(COURSES, default=1) + 1


def next_user_id() -> int:
    return max(USERS, default=1000) + 1


def next_group_id() -> int:
    return max(GROUPS, default=0) + 1


def user_view(userid: int) -> dict[str, Any]:
    """A Moodle-shaped user record with no secrets."""
    user = USERS[userid]
    return {
        "id": user["id"],
        "username": user["username"],
        "firstname": user["firstname"],
        "lastname": user["lastname"],
        "fullname": user["fullname"],
        "email": user["email"],
        "address": "",
        "phone1": "",
        "phone2": "",
        "department": user["department"],
        "institution": user["institution"],
        "idnumber": user["idnumber"],
        "firstaccess": user["firstaccess"],
        "lastaccess": user["lastaccess"],
        "auth": user["auth"],
        "suspended": user["suspended"],
        "confirmed": user["confirmed"],
        "lang": user["lang"],
        "theme": "",
        "timezone": user["timezone"],
        "mailformat": 1,
        "description": user["description"],
        "city": user["city"],
        "country": user["country"],
        "profileimageurlsmall": "",
        "profileimageurl": "",
        "roles": list(user["roles"]),
    }


reset()
