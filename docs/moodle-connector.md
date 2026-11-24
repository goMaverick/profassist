# Moodle connector

Each university connects its own Moodle site from **Admin ? Moodle**
(`/admin/integrations/moodle`). One row in `pa_moodle_connections` holds the site
address, the encrypted web-service token, the course scope, and the push flag.

## Who can change it

Creating, updating, testing, and deleting a connection requires the global
`is_app_admin` flag and an organisation that the admin belongs to. Reading
`/profassist/moodle/status` stays available to a workspace member because the
grading and outline pages show the redacted sync state there.

The legacy `POST /profassist/moodle/sync` and `POST /profassist/moodle/test`
still exist, but now require an app admin. A professor who presses **Sync from
Moodle** on the grading page receives a 403 until an admin runs the sync.

## The token

- Stored as `enc:` Fernet ciphertext produced by `app.core.crypto` with
  `SECRET_KEY`. Only the last four characters are kept in clear, as a hint.
- Never returned by the API. The connection view reports `token_state` and
  `token_hint` only.
- A blank token on update keeps the stored ciphertext. A non-blank token rotates
  it and resets the status to `unverified`.
- Deleting a connection clears the ciphertext and sets the status to `disabled`.
- Any error path strips `wstoken=...` and `token=...` before the message reaches
  storage, a log line, or an API response. `httpx` error strings are redacted in
  the same helper.

## Address rules (SSRF)

- `https://` is required in production. Plain `http://` is a development-only
  convenience and needs `MOODLE_ALLOW_PRIVATE=true`.
- Loopback, private, link-local, CGNAT, and unsupported schemes are rejected.
- `http://localhost` is accepted only when `MOODLE_ALLOW_PRIVATE=true`.
- Host names are resolved and rejected if any address is private.

## Course scope and reads

- `course_scope` is `{"mode": "all"}` or
  `{"mode": "idnumbers", "idnumbers": [...]}` (`shortnames` is also accepted).
  The connector uses `core_course_get_courses_by_field` for a named scope and
  drops the Moodle front page from `core_course_get_courses`.
- Enrolled students come from `core_enrol_get_enrolled_users` with
  `options[0][withcapability]=mod/assign:submit` and `onlyactive=1`; the
  `idnumber` becomes the student number.
- Submissions come from `mod_assign_get_submissions` with `status=submitted`,
  keep the latest attempt only, and use group names when Moodle supplies them.
- Rubrics keep `criterionid`, `levelid`, `score`, and the maximum level.
- Timeouts are connect 5s / read 30s / write 10s, redirects are followed, and an
  idempotent read is retried once on 429/502/503/504.
- Moodle `errorcode` values map to 403 (`required_capability_exception`), 422
  (`invalid_parameter_exception`), or 503 (service/config errors). A
  configuration error is never reported as a 502.

## Environment fallback

`MOODLE_BASE_URL` and `MOODLE_WS_TOKEN` are used only when an organisation has no
connection row. The scheduled sync refuses to fan that global token across
universities: once any org has a row, or when more than one org is a sync target,
orgs without their own connection are skipped.

## Integrity board after a sync

The demo simulator's six submissions share three long passages. A sync compares
the scrubbed text and registers the pairs on the in-memory integrity board, so
`/integrity` shows the A/B method, C/D findings, and E/F introduction pairs
immediately. The board is process-local, like the seeded demo board; restarting
the app clears it and the next sync rebuilds it. A course with no shared wording
is not added.

## Activity logs (demo-only function)

The bundled simulator (`backend/mock_moodle/`) exposes
`local_profassist_get_activity`. It is **not** a stock Moodle function; a real
site will refuse it (`invalidfunction`). The sync treats that refusal as a data
gap, not a failed sync, and continues with courses, students, and submissions.

When rows arrive, the connector keeps the 14 allowlisted dropout columns in
`pa_moodle_activity.features` and the students page scores them. The score is
advisory: nothing changes enrolment, messages, or marks. Both
`/profassist/moodle/connection` and `/profassist/moodle/status` report
`activity_logs.available = true` only when at least one feature row is stored.
