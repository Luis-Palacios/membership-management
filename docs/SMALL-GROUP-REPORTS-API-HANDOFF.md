# Small group reports: report endpoints, roster, not-filed meetings

Handoff spec for the membership-management side of **small group reports**. Read the cross-repo
spec first: `../docs/specs/small-group-reports.md` (workspace folder `members-management/docs/specs/`);
its rules are referred to as *rule N*. It builds on small group leader access
(`../docs/specs/small-group-leader-access.md`, *access rule N*), which must be on `main` first:
this work reuses `require_roles`, `FULL_ACCESS_ROLES` / `SCOPED_ROLES` (`api/access.py`), the small
group scope dependency and `get_current_member` / `CurrentMemberDep`.

The tables already exist (`SmallGroupReport`, `SmallGroupReportAttendance`, migration
`1282e2f6b5ff`, seeded by `data/seed/small_group_reports.py`). **No migration is expected**;
confirm with `uv run alembic check`.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`small-group-reports`** branch (the same name in every repo). Each stage must pass
`uv run ruff check .` and `uv run ty check`, and be tried against the local API (`fastapi dev`,
`/docs`, or `TestClient` with the claims dependency overridden, as earlier stages did) as each role:
`admin`, `elder` (linked and unlinked), `smallGroupLeader` (in and out of scope, former leader,
leader of a closed group), `deacon` with no member, `user`. There's no test runner yet, so note in
*Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, every mutating
route has its own `rate_limit(...)` scope, service errors are domain exceptions the router maps to
HTTP codes, and "today" is `church_today()` (`api/church_time.py`). Routes doing blocking database
work stay plain `def`. Put report code next to the small group code (`data/small_groups/`,
`api/routers/small_group_reports.py`, `api/schemas/small_group_reports.py`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Roster for a date, church Sunday, missed streaks | [ ] | |
| 2. Create and detail (observation visibility) | [ ] | |
| 3. Edit and delete | [ ] | |
| 4. List with not-filed meetings, and the summary | [ ] | |
| 5. Docs | [ ] | |

### Decisions and deviations

- (none yet)

## Who can do what

All routes: `admin`/`elder` → every group; `smallGroupLeader`/`deacon` → groups in scope
(access rules 2, 3, 11), anything else 404 for a single item and filtered out of lists; any other
role → 403.

| Route | Full | Scoped | Notes |
| --- | --- | --- | --- |
| `GET /small-group-reports` | all | in scope | not-filed rows only for open groups |
| `GET /small-group-reports/summary` | all open groups | open groups in scope | |
| `GET /small-groups/{id}/report-roster` | yes | in scope | 409 if closed |
| `POST /small-groups/{id}/reports` | needs a member (rule 5) | in scope, must lead on that date | 409 if closed |
| `GET /small-group-reports/{id}` | yes | in scope | observations per rule 9 |
| `PATCH /small-group-reports/{id}` | yes | in scope | 409 if closed |
| `DELETE /small-group-reports/{id}` | yes | in scope | 409 if closed |

**Observation visibility (rule 9):** `observations_visible = role in FULL_ACCESS_ROLES or
(current_member is not None and current_member.id == report.submitted_by_member_id)`. Admins and
elders see them; scoped roles only on reports their member submitted. Compute it once per request in the service and pass it to the mapping, so no
route can leak an observation by accident.

## Shapes

Dates are `"YYYY-MM-DD"`, timestamps ISO with offset. Names are the member's first and last name
as stored; the staff app builds initials.

```jsonc
// Report detail (GET /small-group-reports/{id}, POST and PATCH responses)
{
  "id": 412,
  "smallGroup": { "id": 3, "name": "Jóvenes Bello Horizonte", "meetingAddress": "…", "closedAt": null },
  "meetingDate": "2026-10-08",
  "churchSunday": "2026-10-04",            // rule 12
  "address": "Bello Horizonte, de la rotonda 2 c. al lago, Managua",
  "groupPrayerRequest": "…", "groupPraiseReport": "…", "groupRelevantDiscussion": null,
  "submittedBy": { "memberId": 209, "firstName": "Carlos", "lastName": "Mendoza" },
  "submittedAt": "2026-10-08T21:42:00-06:00",
  "observationsVisible": true,
  "attendances": [
    { "memberId": 214, "firstName": "Andrea", "lastName": "Gutiérrez",
      "role": "leader",                     // role in the group on the meeting date
      "attendedGroup": true, "attendedChurch": true,
      "missedStreak": 0,                    // rule 11, before this meeting
      "observation": null }                 // key omitted entirely when observationsVisible is false
  ],
  "totals": { "roster": 8, "attendedGroup": 7, "attendedChurch": 6, "observations": 3 }, // "observations" omitted when not visible
  "permissions": { "canEdit": true, "canDelete": true }  // false for closed groups
}

// Create / edit body (PATCH replaces the whole report)
{
  "meetingDate": "2026-10-15",
  "address": "…",                          // optional, ≤ 255; blank → null
  "groupPrayerRequest": "…",               // optional, ≤ 1024; blank → null
  "groupPraiseReport": "…",                // optional, ≤ 1024
  "groupRelevantDiscussion": "…",          // optional, ≤ 1024
  "attendances": [
    { "memberId": 214, "attendedGroup": true, "attendedChurch": true, "observation": null } // observation ≤ 1024
  ]
}

// Roster (GET /small-groups/{id}/report-roster?date=2026-10-15)
{
  "smallGroup": { "id": 3, "name": "…", "meetingAddress": "…", "meetingDay": 4, "closedAt": null },
  "meetingDate": "2026-10-15",
  "churchSunday": "2026-10-11",
  "existingReportId": null,                 // set when a report already exists for that date (rule 1)
  "people": [
    { "memberId": 214, "firstName": "Andrea", "lastName": "Gutiérrez", "role": "leader",
      "joinedAt": "2026-02-02", "missedStreak": 0 }
  ]                                         // leader, then co-leaders, then members, each by name
}

// List (GET /small-group-reports?smallGroupId=&from=&to=&status=all|filed|notFiled&q=&page=1&pageSize=25)
{
  "items": [
    { "kind": "report", "id": 412, "smallGroup": { "id": 3, "name": "…", "closedAt": null },
      "meetingDate": "2026-10-08",
      "submittedBy": { "memberId": 209, "firstName": "Carlos", "lastName": "Mendoza" },
      "submittedAt": "…", "rosterCount": 8, "attendedGroupCount": 7, "attendedChurchCount": 6 },
    { "kind": "notFiled", "smallGroup": { "id": 5, "name": "…", "closedAt": null }, "meetingDate": "2026-10-09" }
  ],
  "counts": { "all": 11, "filed": 8, "notFiled": 3 },   // for the status filter, ignoring `status`
  "total": 11, "page": 1, "pageSize": 25
}

// Summary (GET /small-group-reports/summary)
[
  { "smallGroup": { "id": 3, "name": "…", "meetingDay": 4, "closedAt": null },
    "role": "leader",                       // caller's role in the group; null for full roles
    "lastReport": { "id": 412, "meetingDate": "2026-10-08", "rosterCount": 8, "attendedGroupCount": 7,
                    "submittedBy": { "memberId": 209, "firstName": "Carlos", "lastName": "Mendoza" } },
    "notFiledDates": [] }
]
```

## Errors

Router mapping (messages are English; the staff app matches on status + a phrase from `detail`):

| Exception | Status | `detail` |
| --- | --- | --- |
| `ReportAlreadyExistsError(existing_id)` | 409 | "There's already a report for this group on that date." (body also has `existingReportId`) |
| `MemberRequiredToSubmitError` | 409 | "Link your account to a member to submit reports." |
| `SmallGroupClosedError` (existing) | 409 | existing closed-group message |
| `FutureMeetingDateError` | 422 | "The meeting date can't be in the future." |
| `AttendanceMismatchError` | 422 | "The attendance doesn't match the group's members on that date." |
| `NotGroupLeaderOnDateError` | 422 | "You didn't lead this group on that date." |
| out of scope / not found | 404 | existing not-found message |

## Stage 1: Roster for a date, church Sunday, missed streaks

**Files:** `data/small_groups/queries.py`, `results.py`, `services.py`, new
`api/routers/small_group_reports.py`, `api/schemas/small_group_reports.py`, `api/main.py`.

- `church_sunday(d: date) -> date`: `d - timedelta(days=d.isoweekday() % 7)` (rule 12). Put it
  next to `church_today()` or in the services module; both apps rely on the API's value.
- `roster_on_date_query(small_group_id, d)`: memberships whose period covers `d` (rule 3), joined
  to `Member`, with the role of that period. If a member has two periods touching `d` (role change
  that day), take the one active at the end of the day (`left_at` null or `> d`, else the latest).
- `missed_streaks(session, small_group_id, member_ids, before: date) -> dict[int, int]` (rule 11):
  walk that group's reports before `before`, newest first, and count each member's leading run of
  `attended_group = false`. One query over attendances joined to reports, ordered by date desc,
  folded in Python; limit to the last ~12 reports, which is plenty for a hint.
- `GET /small-groups/{id}/report-roster?date=`: scope check as group detail; 422 future date;
  409 closed group; returns the roster shape with `existingReportId` and `churchSunday`.
- Domain exceptions from *Errors* defined now, mapped in the router.

## Stage 2: Create and detail

- `create_report(session, group, body, *, submitter_member_id, caller_is_scoped, today)`:
  - closed → `SmallGroupClosedError`; `meetingDate > today` → `FutureMeetingDateError`;
  - existing `(group, date)` → `ReportAlreadyExistsError(existing.id)`; also catch the unique
    violation on commit (`_commit_or_raise_conflict` pattern) for the race;
  - attendance `memberId`s must equal the roster's set exactly → `AttendanceMismatchError`;
  - scoped caller: their member must have `leader`/`co_leader` on that date →
    `NotGroupLeaderOnDateError` (the model's comment: "the service layer checks…").
  - trims text, blank → null; `submitted_at` from the server default.
- `POST /small-groups/{id}/reports` (`rate_limit("small-group-reports:write")`): role check;
  `get_current_member`, none → `MemberRequiredToSubmitError` (rule 5); 201 with the detail shape.
- `GET /small-group-reports/{id}`: load with the scope filter **in the query** (as access spec
  says: filter by the scope's ids, don't load then compare); 404 otherwise. Build attendances with
  each member's role on the meeting date and `missedStreak`; include `observation` and
  `totals.observations` only when `observationsVisible` (rule 9). `permissions` = not closed.

## Stage 3: Edit and delete

- `PATCH /small-group-reports/{id}`: same validation as create, against the (possibly new)
  `meetingDate`; uniqueness ignores the report itself. Update attendance rows **in place by
  `memberId`** (insert new members, delete rows no longer in the roster) so observations survive.
  If the caller can't see observations, ignore any `observation` in the body and keep stored ones.
  `submitted_by_member_id` and `submitted_at` never change (rule 6). Closed → 409.
- `DELETE /small-group-reports/{id}`: 204; attendances cascade; closed → 409.
- Both have their own `rate_limit` scope.

## Stage 4: List with not-filed meetings, and the summary

- `GET /small-group-reports`: params from *Shapes*. Defaults: `from` = today − 42 days,
  `to` = today, `status=all`, `pageSize=25` (max 100).
  - Filed rows: one query over reports in scope and range, with the three counts as aggregates
    over attendances. `q` matches group name or submitter name (case-insensitive, accents as the
    members search already does).
  - Not-filed rows (rule 10): for open groups in scope with a `meeting_day` and matching
    `smallGroupId`/`q`, the weekday dates in `[max(from, today − 28), min(to, today − 1)]`, while
    open and with an active leader/co-leader (one query of leadership periods per group set), minus
    dates that have a report. Groups in scope are few, so build these in Python.
  - Merge, sort by `meetingDate` desc then group name, compute `counts` before the status filter,
    then filter by `status` and page in memory.
- `GET /small-group-reports/summary`: open groups in scope, ordered by name; `role` is the
  caller's role in the group for scoped callers (null for full roles); `lastReport` is the newest
  report; `notFiledDates` uses the same rule-10 helper as the list. No observations anywhere.

## Stage 5: Docs

- `docs/ARCHITECTURE.md`: the report routes and the observation rule in a few lines.
- `docs/ROADMAP.md`: mark reports done.
- Tick the stages here; then in the workspace spec, trim what now lives in code (workspace
  `CLAUDE.md`: keep only decisions).
- Tell the staff-app session the final shapes if anything moved from this document.

## Not in this spec

- Any new column or table (drafts, observation author, edit history).
- Reminders for not-filed reports.
- Role checks on `/members`, `/people`, `/applications` (leader access spec, *Not in this spec*).
