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
| 1. Roster for a date, church Sunday, missed streaks | [x] | 0ae1e15 |
| 2. Create and detail (observation visibility) | [x] | 43d68c8 |
| 3. Edit and delete | [x] | 322e273 |
| 4. List with not-filed meetings, and the summary | [x] | 7f43679 |
| 5. Docs | [x] | see git log |

### Decisions and deviations

- Verification: no test runner, so each stage was tried with scratch scripts (kept outside the repo)
  that seed `ZZ`-prefixed members, groups and reports in the local members DB, call the API through
  `TestClient` with `get_current_claims` overridden, and delete the rows afterwards. Actors: admin and
  elder (linked and unlinked), leader and co-leader in scope, leader of another group, former leader,
  leader of a closed group, deacon with no member, deacon who is only a plain member, `user`.
- **Names are one `name`, not `firstName`/`lastName`.** `members.name` is a single column (and the
  staff app's `initialsOf(name)` takes a full name), so every person in a report shape is
  `{ memberId, name }` instead of `{ memberId, firstName, lastName }`. Applies to `submittedBy`,
  attendance rows, roster people and the summary. The staff-app session must use `name`.
- Stage 1: `church_sunday` lives in `data/small_groups/services.py` (the data layer can't import from
  `api/`); the router imports it. The roster's `date` query parameter is required.
- Stage 1: the roster checks closed (409) before future (422), the same order as create.
- Stage 2: the duplicate-date 409 body is `{ "detail": "There's already a report…", "existingReportId": N }`.
  A plain `HTTPException` can't add a key, so the router raises `DuplicateReportHTTPError` and
  `main.py` has a handler for it. Other errors are plain `{ "detail": … }`.
- Stage 2: the route's 404 for a report is "Small group report with ID N not found." (the handoff's
  "existing not-found message" is the group's, which would be misleading here).
- Stage 2: observation keys are omitted with `response_model_exclude_unset=True`: the mapping only
  passes `observation` / `totals.observations` when visible. `build_report_detail` already nulls
  every observation for a viewer who can't see them, so a mapping slip can't leak one.
- Stage 2: text trimming and blank to null happen in the request schema (`ReportBodySchema`), which
  both create and edit use; the service gets already-clean values. Checks run in this order: closed,
  future, duplicate date, attendance set (exactly the roster, no repeats), then "led on that date"
  for scoped callers. A caller with no member gets 409 before any of them.
- Stage 2: rate-limit scopes are named like the existing ones (`create_small_group_report`, 20/minute),
  not `small-group-reports:write`.
- Stage 2 verification (scratch script, `TestClient`): create as elder (linked), elder and admin
  with no member (409), leader and co-leader (201, own observation visible), a co-leader who only
  started leading 3 days ago (422 for an earlier date, 201 for a date they led), group leader of
  another group, former leader, leader of a closed group, deacon with no member, deacon who is only
  a plain member, `user` (403); duplicate, missing/extra/repeated/wrong attendance, future date,
  over-long text and observation, closed group (elder and its own leader); detail for every actor
  on a report by the leader (other leaders get no `observation` keys and no trace of the text),
  a seeded report by the co-leader, a closed group's report (leaders when it closed see it,
  `permissions` false), unknown ids. The unique-violation race was forced by stubbing the pre-check.


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
      "joinedAt": "2026-02-02",             // start of the membership period covering the meeting date; null if memberships changed since
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
- Stage 3: edit validates like create (closed, future, duplicate date ignoring the report itself,
  attendance set equals the roster on the new date) but does **not** repeat the "led on that date"
  check: that is a rule about submitting (rule 5), the submitter never changes, and rule 6 lets any
  current leader or co-leader edit.
- Stage 3: rule 9 on edit uses one helper, `observations_visible_to`, shared with the detail. A caller
  who may see observations (admin, elder, the submitter) replaces them with what they send (omitted
  or null clears); anyone else leaves every stored observation alone, and a row inserted by such a
  caller is created with none.
- Stage 3 verification (scratch script, `TestClient` plus direct DB reads): a co-leader editing the
  leader's report can't read or overwrite observations; the submitter and an unlinked elder can;
  attendance rows keep their ids; moving the date adds and removes rows to match the new roster;
  collision with another report's date is 409 with `existingReportId`; the submitter and
  `submitted_at` are unchanged after every edit; closed-group PATCH/DELETE as elder, admin and the
  group's own leader (409); PATCH and DELETE for all eleven actors, including that refused callers
  change and delete nothing; delete removes the attendance rows.
- Stage 4: **not-filed rows are for open groups only**, as the handoff says. Spec rule 10's wording
  ("while the group was open, `date <= closed_at`") could be read to also list a closed group's last
  missed meetings, but a closed group takes no report (rule 8), so such a row could never be acted
  on. Say so if the spec's reading is wanted instead; it is one `closed_at` condition in
  `not_filed_dates` (`services.py`).
- Stage 4: "had an active leader or co-leader" is checked **per date** (a leadership period covering
  that date), not against today, so a group whose leader started 10 days ago shows no not-filed
  meetings before that. The window is `[max(from, today - 28), min(to, today - 1)]`, so an earlier
  `from` shows older filed reports but never older not-filed meetings.
- Stage 4: `q` is matched in Python (case and accent folding with `unicodedata`), against the group
  name and, for filed reports, the submitter's name. The "members search" the handoff mentions doesn't
  exist server-side, and `unaccent` would need an extension, so no migration. Cheap here because the
  filed query is already bounded by scope and date range and paging is in memory by design.
- Stage 4: `notFiledDates` in the summary are newest first (like the list). `role` is the caller's
  *current* role in the group (always leader or co-leader for a scoped caller on an open group); null
  for admins and elders even when they are members. The summary and the list never read observations.
- Stage 4: a scoped caller who filters by a group outside their scope (`smallGroupId`) gets an empty
  list, not a 404 ("filtered out of lists"). `from` after `to` gives an empty list rather than a 422.
- Stage 4: `/small-group-reports/summary` is declared before `/small-group-reports/{report_id}`; swapping
  them makes `summary` fail as a non-integer id.
- Stage 4 verification (scratch script, `TestClient`, seeded `ZZ` groups next to the real seed data,
  which full roles also see, so those checks narrow with `q=zz`): defaults; `status`, `smallGroupId`,
  `from`/`to`, `q` with accents and capitals (submitter and group), paging and bad parameters (422);
  a not-filed meeting never today, never older than 28 days, never in a closed group or a group with no
  meeting day, and not before the leader started; list and summary for all eleven actors (empty, not
  an error, for scoped roles with nothing to see; 403 for `user`); no observation text anywhere in the
  list or summary even though the seeded reports have observations. Also a smoke run on the real seed.
- Stage 5: `docs/ARCHITECTURE.md` (a *Small group reports (built)* section), `docs/ROADMAP.md` and the
  one-line pointer in this repo's `CLAUDE.md`. **The workspace spec
  (`docs/specs/small-group-reports.md`) is not trimmed yet:** the staff-app stages are still open, and
  the spec counts as done only when every repo's log is ticked. Two things to carry there when it is
  trimmed or the staff-app session starts: names are a single `name` (not first/last), and the not-filed
  rows are open groups only (see *Decisions* above).
