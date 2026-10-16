# Architecture (target / vision)

This describes where the project is headed, not what's built yet — for current implementation state, see the root `CLAUDE.md`.

## System shape

A single microservice — membership management (assimilation): membership applications, members, small groups and small-group reports — augmenting an existing church web application (SQL Server DB, real users) by adding a new component alongside it rather than extending it directly.

- Uses the **existing SQL Server DB** via SQLAlchemy (this is the code that exists today, under `src/membership_management/data/assimilation/`).
- FastAPI surface to list, review, and approve membership applications.
- Planned areas beyond applications: members management, small groups, and small-group reports.

## Permissions (built)

Rules: `docs/specs/roles-and-permissions.md` (workspace repo); this side:
`docs/ROLES-PERMISSIONS-API-HANDOFF.md`. **No role names are checked here.** auth-server's
`statements.ts` is the only role → permission map; it puts the caller's permissions in the JWT as
`perms` (`Record<resource, action[]>`), and every route checks those:

- `api/jwt_auth.py`: `AuthClaims.perms` (missing → `{}`, fail closed), `has_permission(claims,
  resource, action)` and `require_permission(resource, *actions)` (all-of, 403).
- **Permissions say what, scope says on which records** (`api/access.py`). `SmallGroupScopeDep`:
  403 without `smallGroups: view`; with `smallGroups: all` every group, otherwise the groups the
  caller's member leads or co-led when they closed. `MemberScopeDep`: with `members: all` every
  member, otherwise members active in an open group of that small group scope. Out of scope is 404
  (same message as missing); a missing permission is 403.
- Leadership rule 9: adding, promoting to or changing a `leader` row needs `smallGroups:
  setLeader`; without `smallGroups: all` you can't change your own row. Report observations need
  `smallGroupReports: viewObservations`, or being the submitter. A member's `email` can be changed
  only with `members: all`.
- Not permission-gated: `GET /me` (any valid JWT, `pending` included), `GET /health`,
  `/internal/*` (shared `X-Internal-Token`).

What each role gets today (from auth-server's statements; ✓ all records, *scope* only its
records with 404 elsewhere, — 403). `smallGroupLeader` and `deacon` are the same for now; `user` and
`pending` have no permissions and get 403 on every route below.

| Route | Permission | admin, elder | smallGroupLeader, deacon |
| --- | --- | --- | --- |
| `GET /small-groups`, `GET /small-groups/{id}` | `smallGroups: view` (+ scope) | ✓ | scope |
| `POST /small-groups` | `smallGroups: create` | ✓ | — |
| `PATCH /small-groups/{id}` | `smallGroups: update` + scope | ✓ | scope |
| `POST /small-groups/{id}/close` | `smallGroups: close` + scope | ✓ | — |
| `PUT /small-groups/{id}/leader` | `smallGroups: setLeader` + scope | ✓ | — |
| `POST`, `PATCH`, `DELETE /small-groups/{id}/members[/{memberId}]` | `smallGroups: manageMembers` + scope, rule 9 | ✓ | scope, no leader rows, not own row |
| `GET /small-group-reports`, `/summary`, `/{id}`, `GET /small-groups/{id}/report-roster` | `smallGroupReports: view` + scope | ✓ (observations) | scope (own observations) |
| `POST /small-groups/{id}/reports`, `PATCH`, `DELETE /small-group-reports/{id}` | `smallGroupReports: create` / `update` / `delete` + scope | ✓ | scope |
| `GET /small-group-reports/week` | `smallGroups: all` + `smallGroupReports: viewObservations` | ✓ | — |
| `GET /members` | `members: view` + `all` | ✓ | — |
| `GET /members/options` | `members: search` | ✓ | ✓ (id and name only) |
| `GET /members/{id}` | Own member: none (any role, rule 11). Others: `members: view` + members scope | ✓ | own + scope |
| `POST /members` | `members: create` | ✓ | — |
| `PATCH /members/{id}` | `members: update` + members scope; `email` needs `all` | ✓ | scope, no `email` |
| `PUT`, `DELETE /members/{id}/user` | `members: link` | ✓ | — |
| `GET /applications/recents`, `/recents/count`, `/{id}` | `membershipApplications: view` | ✓ | — |
| `POST /applications/approve`, `/reject` | `membershipApplications: approve` / `reject` | ✓ | — |
| `GET /people/{id}/events`, `/first-assistance` | `membershipApplications: view` | ✓ | — |
| `GET /me` | none (any valid JWT) | ✓ | ✓ |

A new role, or a change to what a role can do, is an auth-server change only; nothing here
changes unless a new *action* needs a new check.

## Small group reports (built)

A group files one report per meeting date: the group's text fields plus one attendance row for every member whose membership covers that date. Rules and contracts: `docs/specs/small-group-reports.md` (workspace repo) and `docs/SMALL-GROUP-REPORTS-API-HANDOFF.md`. Code: `api/routers/small_group_reports.py`, `data/small_groups/{queries,results,services}.py`.

- Routes: `GET /small-group-reports` (filed reports and computed not-filed meetings, counts, paging), `GET /small-group-reports/summary` (dashboard), `GET /small-groups/{id}/report-roster?date=`, `POST /small-groups/{id}/reports`, `GET|PATCH|DELETE /small-group-reports/{id}`. Access is `smallGroupReports` permissions plus the small group scope (`SmallGroupScopeDep`, see *Permissions*); closed groups are read-only (409).
- **Observations are private (rule 9).** An attendance row's pastoral `observation` is returned, and editable, only with `smallGroupReports: viewObservations` and for the report's submitter. `build_report_detail` decides it once per request and nulls every observation otherwise; the schema then omits the key. Lists and the summary never carry observations.
- "Not filed" is computed, never stored: `recent_meetings` returns, per open group with a meeting day, every date in the last 28 days before today that had a leader or co-leader, with the report id on it or None; `not_filed_dates` is the entries without one.
- **Groups dashboard** (`docs/specs/groups-dashboard.md`, `docs/GROUPS-DASHBOARD-API-HANDOFF.md`). The summary adds `hasLeader` (an open leader or co-leader period today) and `recentMeetings` (the list above, newest first). `GET /small-group-reports/week?date=` (`smallGroups: all` + `smallGroupReports: viewObservations`, since it carries observation *counts*, rule 9) gives every open group's status for the Sunday-to-Saturday week of `date` (default today): `submitted`, `notFiled`, `today`, `upcoming`, `noLeader` or `noMeetingDay`, first match wins (`get_report_week`). A week after the current one is 422; closed groups never appear.
- **No meeting** (rule 13, `docs/SMALL-GROUP-NO-MEETING-API-HANDOFF.md`). A leader can record that the group didn't meet on a date: a `small_group_reports` row with `held = false` and an optional `not_held_reason` (≤ 255), no attendance rows and no group texts (two CHECKs). Create takes `{held: false, meetingDate, notHeldReason}` (a missing `held` means a held report); the unique (group, date) makes a date a meeting or a no meeting, never both. A held report can be created over a no meeting only with `replacesNoMeeting: true` (one transaction); a report never changes kind on PATCH (422), and the duplicate 409 and roster carry `existingReportHeld`. It is filed for rule 10 (never Not filed) but is not a Last report, not in `filed` counts (`notHeld` instead), and doesn't take a missed-streak window slot (`held = true` filters in `latest_report_ids_query` and `recent_attendance_marks_query`). The list `status` adds `notHeld`, `recentMeetings[].held` is null when not filed, and the week status adds `notHeld` (no held report but a no meeting).
- Names in these routes are the member's single stored `name` (members have no first/last name columns).

## Infra / deployment target
- Docker → Kubernetes → Terraform, deployed to AWS or GCP.
- Basic CI/CD, likely GitHub Actions.
- Caching and logging as cross-cutting concerns (mechanism TBD).
- Notifications: email and WhatsApp.

## Why this shape
This is primarily a learning project (modern Python/FastAPI stack, agentic dev workflows with Claude Code, eventually a real deployed system) that also needs to work for a small real user base (~20 people at one church).
