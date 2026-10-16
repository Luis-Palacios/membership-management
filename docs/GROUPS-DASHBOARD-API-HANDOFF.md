# Groups dashboard: summary fields and the week endpoint

Handoff spec for the membership-management side of the **groups dashboard**. Read the cross-repo
spec first: `../docs/specs/groups-dashboard.md` (workspace folder `members-management/docs/specs/`);
its rules are referred to as *rule N*. It builds on small group reports
(`../docs/specs/small-group-reports.md`, *reports rule N*) and this repo's
`docs/SMALL-GROUP-REPORTS-API-HANDOFF.md`, which are on `main`.

**No migration is expected**; confirm with `uv run alembic check`.

Work through it **stage by stage**, one reviewable commit per stage, on the **`groups-dashboard`**
branch (the same name in every repo). Each stage must pass `uv run ruff check .` and
`uv run ty check`, and be tried against the local API (`TestClient` with the claims dependency
overridden, as the reports stages did) as each role: `admin`, `elder` (linked and unlinked),
`smallGroupLeader` (in and out of scope, former leader), `deacon` with no member, `user`. There's no
test runner yet, so note in *Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, service errors are
domain exceptions the router maps to HTTP codes, "today" is `church_today()`, and routes doing
blocking database work stay plain `def`. Everything goes next to the report code
(`data/small_groups/`, `api/routers/small_group_reports.py`, `api/schemas/small_group_reports.py`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Summary: `hasLeader` and `recentMeetings` | [ ] | |
| 2. Week endpoint | [ ] | |
| 3. Docs | [ ] | |

### Decisions and deviations

- [Anything decided during implementation, or where the build differs from this document, and why.]

## Who can do what

| Route | `admin` / `elder` | `smallGroupLeader` / `deacon` | others |
| --- | --- | --- | --- |
| `GET /small-group-reports/summary` | all open groups | open groups in scope | 403 (unchanged) |
| `GET /small-group-reports/week` | all open groups | **403** | 403 |

The week endpoint returns observation **counts**, which only full roles may know about (reports
rule 9), hence full roles only: `Depends(require_roles("admin", "elder"))`, as `small_groups.py`
does for its admin routes. The summary's new fields carry no observations.

## Shapes

Full shapes are in the cross-repo spec, *Contracts*. Field notes:

- `recentMeetings[].reportId`: the report on that date, null when not filed. Newest first.
- `hasLeader`: some `leader` or `co_leader` membership of the group has `left_at` null today.
- Week `leaders`: the same active periods, with the member's `name`; leader first, then co-leaders
  by name. Empty for `noLeader` groups whose leader left (the row still shows).
- Week `meetingDate`: always the week's date on `meetingDay` (even for `submitted`, where the report
  can be on another day); null when `meetingDay` is null.
- Week `reports[].observationCount`: attendance rows of that report with a non-null `observation`.
- Dates are `"YYYY-MM-DD"`; names are a single `name` (as in the reports API).

## Errors

| Exception | Status | `detail` |
| --- | --- | --- |
| `FutureWeekError` | 422 | "The week can't be in the future." |
| not a full role | 403 | existing `require_roles` message |

Only a date **after the current week's Saturday** is refused. A later day in the current week is
fine (it's the same week).

## Stage 1: Summary, `hasLeader` and `recentMeetings`

**Files:** `data/small_groups/services.py`, `results.py`, `api/schemas/small_group_reports.py`,
`api/routers/small_group_reports.py`.

- Generalize `not_filed_dates` into one rule-10 helper that returns, per open group with a meeting
  day, **every** candidate date in `[start, end]` (on the weekday, with a leader or co-leader period
  covering it) with the report id on that date or None, newest first. Keep `not_filed_dates` as a thin
  wrapper (or replace its callers) so `list_reports` and the summary's `notFiledDates` stay exactly
  as they are. `report_dates_query` needs the report id for this.
- `GroupReportSummary` gains `has_leader: bool` and `recent_meetings: list[RecentMeeting]`
  (`RecentMeeting(date, report_id)`). `has_leader` comes from the leadership periods already loaded
  (one with `left_at` null); don't add a query per group.
- Groups without a meeting day get `recentMeetings: []` (as they get no not-filed dates).
- Schemas: `RecentMeetingSchema(date, report_id)`; `ReportSummaryItemSchema` gains `has_leader` and
  `recent_meetings`.

**Try:** a group whose leader started 10 days ago (only the dates since then); a group with a
co-leader and no leader (`hasLeader` true); a group whose only leader left (`hasLeader` false,
`recentMeetings` keeps the dates while they led); a Sunday-meeting group; today never in the list;
`notFiledDates` unchanged against `main` for the seed data; every role.

## Stage 2: Week endpoint

**Files:** `data/small_groups/queries.py`, `results.py`, `services.py`,
`api/schemas/small_group_reports.py`, `api/routers/small_group_reports.py`.

- `GET /small-group-reports/week?date=YYYY-MM-DD` (`date` optional, default `church_today()`).
  Declare it **before** `/small-group-reports/{report_id}`, like `summary`.
- `get_report_week(session, *, day: date, today: date) -> ReportWeek`:
  - `week_start = church_sunday(day)`, `week_end = week_start + 6 days`. If
    `week_start > church_sunday(today)`, raise `FutureWeekError`.
  - Groups: `report_groups_query(None)`, open only (`closed_at` null), ordered by name.
  - Reports in the week: one query over `[week_start, week_end]` with, per report, roster count,
    attended-group count, attended-church count and **observation count** (aggregates over
    attendances, like `filed_reports_query`; add the observation count there or write a
    `week_reports_query` beside it), plus submitter id and name. Group them by group, newest first.
  - Leadership: reuse `leadership_periods_query` for the per-date test (rule 6.3), and one query for
    the active leaders' names (`left_at` null, role leader/co-leader).
  - Status per rule 6, in that order. `D = week_start + (meeting_day % 7)` days, since the week
    starts on Sunday and `meeting_day` is ISO (Mon 1 … Sun 7): Sunday (7) is `week_start` itself.
  - `isCurrentWeek = week_start == church_sunday(today)`.
- Schemas: `ReportWeekSchema`, `WeekGroupSchema`, `WeekReportSchema`, `WeekLeaderSchema`; `status`
  is a `Literal` of the six values.

**Try:**
- `date` on Sunday, Wednesday and Saturday of the same week → identical response.
- A date in next week → 422; the current week's Saturday → 200.
- A past week: no `today` or `upcoming` statuses; a missed meeting is `notFiled` (the staff app
  labels it).
- Two reports in one week (one on a non-meeting day) → `submitted`, both in `reports`, newest first.
- A report on a non-meeting day only → `submitted`.
- Leader who left mid-week: `D` before the leave date → `notFiled`; after → `noLeader`.
- A group whose meeting day is today → `today` until a report exists.
- A closed group (also closed after the week) → absent.
- A group with no meeting day and no report → `noMeetingDay`; with a report → `submitted`.
- `observationCount` matches the detail for an elder; the response never contains observation text.
- Roles: admin and elder (linked and unlinked) 200; leader, deacon, `user` 403.

## Stage 3: Docs

- `docs/ARCHITECTURE.md`: the week route and the two summary fields in a few lines.
- `docs/ROADMAP.md`: add the groups dashboard as done.
- Tick the stages here. Tell the staff-app session the final shapes if anything moved from this
  document.

## Not in this spec

- Any new column or table.
- Weeks for scoped roles (rule 11).
- Closed groups in past weeks (rule 5).
- Notifications for due reports.
