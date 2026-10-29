# Small group reports: church-wide no meeting (a whole week, every group)

Handoff spec for the membership-management side of **church-wide no meeting**: an admin or elder
marks a whole week as no meeting for every open group at once, with an optional reason, instead of
each leader marking it. It builds on the per-group no meeting
(`docs/SMALL-GROUP-NO-MEETING-API-HANDOFF.md`). *Rule N* = the cross-repo
`../docs/specs/church-wide-no-meeting.md`; *reports rule N* = `../docs/specs/small-group-reports.md`;
*dashboard rule N* = `../docs/specs/groups-dashboard.md`. The staff-app side is
`staff-app/docs/design/CHURCH-WIDE-NO-MEETING.md`.

**Decided (don't re-open):**

- A church-wide no meeting is **one `small_group_no_meeting_weeks` row per week** plus **a normal
  no meeting per group** (`held = false`) that points to it through
  `small_group_reports.no_meeting_week_id`. Every read that already handles no meetings (week
  status, lists, Needs follow-up, replace flow) keeps working; the week row is what makes edit
  reason and undo act on the whole batch.
- Current week, **next week**, or a past week. Whole weeks only.
- Every group **open today** with a `meeting_day`, with or without a leader, gets a no meeting on
  its meeting day in the week, **unless it has any report dated in the week** (held or not, any
  weekday). Skipped ones are never linked to the week.
- Running it again for the same week marks the groups still empty, on the same row, and leaves the
  reason alone. Nothing is marked automatically.
- A no meeting (any, not only church-wide) may be dated up to the end of next week. A held report
  stays today or earlier.
- A leader editing a linked report's reason or date unlinks it. Undo deletes only reports still
  linked.
- No new permission: `smallGroups: all` plus the matching `smallGroupReports` action.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`church-wide-no-meeting`** branch (same name in staff-app). Each stage must pass
`uv run ruff check .` and `uv run ty check`, and be tried against the local API as admin, elder
(linked and unlinked), leader, deacon and user. Keep every convention from the reports handoff
(services/queries/results split, `CamelModel`, domain errors mapped in `_http_error`,
`church_today()`, plain `def` routes, per-route `rate_limit`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration and model | ✅ | `a82e1f0` |
| 2. Next week: week endpoint and future no meetings | ✅ | (this commit) |
| 3. Mark a week (`POST /no-meeting-weeks`) | ⬜ | |
| 4. Edit reason, undo, unlink on leader edit, reads | ⬜ | |
| 5. Seed and docs | ⬜ | |

### Decisions and deviations

- (none yet)

## Data model

New table `small_group_no_meeting_weeks` (model `SmallGroupNoMeetingWeek` in
`data/small_groups/models/small_group_no_meeting_week.py`, exported from `models/__init__.py`):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int identity | PK |
| `week_start` | date | **unique**; always a church Sunday (`church_sunday()`, reports rule 12) |
| `reason` | varchar(255) null | blank → null, like `not_held_reason` |
| `created_by_member_id` | int FK `members.id` | the caller's member (rule 1) |
| `created_at` | timestamptz | `server_default=func.now()` |
| `updated_at` | timestamptz | `server_default=func.now()`, set on edit reason |

CHECK `extract(dow from week_start) = 0` (`week_start_is_sunday`).

`small_group_reports` gains:

- `no_meeting_week_id: int | None`, FK `small_group_no_meeting_weeks.id` **`ON DELETE SET NULL`**,
  indexed.
- CHECK `NOT held OR no_meeting_week_id IS NULL` (`no_meeting_week_only_when_not_held`).
- relationship `no_meeting_week` (no cascade: undo deletes the reports explicitly, rule 10).

## Shapes

All camelCase (`CamelModel`).

### Mark (`POST /no-meeting-weeks`)

Permissions `smallGroups: all` + `smallGroupReports: create`; caller's member required (409
`Link your account to a member…`, the same `MemberRequiredToSubmitError`). Rate limit
`10/minute`, scope `mark_no_meeting_week`.

```jsonc
// Body (extra keys forbidden)
{ "date": "2026-11-04", "reason": "Retiro de la iglesia" }  // any day of the week; reason optional, ≤ 255

// 201 on the first mark, 200 on a re-run (rule 6; the body's reason is then ignored)
{
  "id": 7,
  "weekStart": "2026-11-01",
  "reason": "Retiro de la iglesia",
  "createdBy": { "memberId": 12, "name": "Jorge Ramírez" },
  "createdAt": "2026-10-28T15:04:00Z",
  "updatedAt": "2026-10-28T15:04:00Z",
  "linkedCount": 22,                                   // reports linked after this call
  "marked": 22,                                        // created by this call
  "skipped": { "reported": 3, "noMeetingDay": 1 }
}
```

### Edit reason (`PATCH /no-meeting-weeks/{id}`)

`smallGroups: all` + `smallGroupReports: update`; no member needed. Rate limit `20/minute`.
Body `{ "reason": string | null }` (extra keys forbidden). Sets `reason`, `updated_at` and the
`not_held_reason` of every report still linked, in one transaction (rule 8). Returns the same
shape without `marked` / `skipped`.

### Undo (`DELETE /no-meeting-weeks/{id}`)

`smallGroups: all` + `smallGroupReports: delete`; no member needed. Rate limit `10/minute`.
Deletes every report with that `no_meeting_week_id` (including those of groups closed since; this
does **not** go through `delete_report`, whose closed check is for report edits), then the week
row. 204. Unknown id: 404.

### Week (`GET /small-group-reports/week?date=`)

- Accepts **next week** (rule 11). Two weeks ahead or later: 422 `future` as today.
- Adds `noMeetingWeek`: the shape above without `marked` / `skipped`, or `null`.
- `reports[]` items gain `noMeetingWeekId: int | null`.

### Detail and list

`ReportDetailSchema` and `FiledReportItemSchema` gain `noMeetingWeekId: int | null`. The summary
doesn't change (the dashboard's follow-up dots don't tell the two apart).

## Errors (new or changed)

| When | HTTP | detail |
| --- | --- | --- |
| Mark, edit or undo without `smallGroups: all` or the action | 403 | existing message |
| Mark with no linked member | 409 | existing `Link your account to a member…` |
| Mark a week after next | 422 | existing "The week can't be in the future." |
| A no meeting dated after the end of next week (create or edit) | 422 | existing "The meeting date can't be in the future." |
| A held report dated after today | 422 | unchanged |
| Edit or undo an unknown week | 404 | "No meeting week with ID {id} not found." |

## Stage 1: Migration and model

- The model and column above; import the new model in `models/__init__.py` (and confirm
  `data/models.py` already imports the `small_groups` package).
- `uv run alembic revision --autogenerate -m "add small group no meeting weeks"`; hand-add both
  CHECKs if autogenerate misses them and confirm `ondelete="SET NULL"`. `upgrade head`,
  `downgrade -1`, `upgrade head`; `alembic check` clean.
- Results tuples that the reads will fill (`WeekReportRow`, `FiledReportRow`, `ReportDetail`) gain
  `no_meeting_week_id: int | None = None` **at the end, with a default**, like the no-meeting
  stage 1 did.

## Stage 2: Next week

**Files:** `data/small_groups/services.py`, `api/routers/small_group_reports.py`.

- `_week_bounds(day, today, *, weeks_ahead: int = 0)`: refuse `week_start > church_sunday(today) +
  7 * weeks_ahead`; `is_current_week` unchanged. `get_report_week` passes `weeks_ahead=1`;
  `get_report_shared` (prayer & follow-up) keeps 0 (rule 11).
- Check that a next-week view comes out right with today's `_week_group` logic: every `D` is after
  today, so groups are `upcoming`, `noLeader` (tested against today) or `noMeetingDay`, and marked
  ones `notHeld` (a no meeting beats them). It shouldn't need a change; note it if it does.
- `_validate_date` gains `held: bool`: a held report keeps `meeting_date > today` →
  `FutureMeetingDateError`; a no meeting raises it only past `church_sunday(today) + 13` (the
  Saturday of next week). `create_report` and `update_report` pass `body.held`. Name the limit
  once (`_last_no_meeting_date(today)`) so stage 3 uses the same one.
- Try: a leader POSTs a no meeting for next Wednesday (201), for the week after (422), and a held
  report for tomorrow (422).

## Stage 3: Mark a week

**Files:** `api/schemas/small_group_reports.py` (`NoMeetingWeekBodySchema`,
`NoMeetingWeekSchema`, `NoMeetingWeekMarkSchema`), `api/routers/small_group_reports.py`,
`data/small_groups/services.py`, `queries.py`, `results.py`.

`mark_no_meeting_week(session, *, day, reason, member_id, today) -> NoMeetingWeekMark`:

1. `_week_bounds(day, today, weeks_ahead=1)`.
2. Get or create the week row for `week_start`. A new row takes `reason`; an existing one keeps its
   own (rule 6). The response is 201 when the row was created, else 200.
3. `_open_report_groups(session, None)`; groups without `meeting_day` → `skipped.noMeetingDay`.
4. One query for the group ids with any report dated in `[week_start, week_end]`
   (`reported_group_ids_in_week_query`, held and not held) → `skipped.reported`.
5. For the rest, insert `SmallGroupReport(held=False, meeting_date=D, not_held_reason=week.reason,
   submitted_by_member_id=member_id, no_meeting_week_id=week.id)`. `D` from the same helper
   `_week_group` uses for the meeting date. No leader check (full role, reports rule 5).
6. One commit. A lost race (a leader marking the same date, the unique `(group, date)`, or another
   elder creating the same week, the unique `week_start`): roll back and run steps 2–6 **once**
   more; a second failure is raised.

The route maps `member is None` to `MemberRequiredToSubmitError` before calling, like
`post_small_group_report`, and sets the status code from the result.

Try: mark this week with a reason (201, counts right, the week shows `notHeld` everywhere it
should and `noMeetingWeek`); a group with a held report and one a leader marked beforehand stay
as they were; run it again (200, `marked: 0`); open a new group and run it again (`marked: 1`, same
`id`); an unlinked elder (409); a leader (403); two weeks ahead (422).

## Stage 4: Edit reason, undo, unlink, reads

**Files:** same as stage 3, plus `update_report` in `services.py`.

- `update_no_meeting_week_reason` and `delete_no_meeting_week` per *Shapes*; each one transaction.
- `update_report`, not-held branch: when the report has a `no_meeting_week_id` and the body
  **changes** `not_held_reason` or `meeting_date`, set it to null (rule 9). Same values → stays
  linked (the staff app's dialog re-sends the date).
- Reads: `week_reports_query`, `filed_reports_query` and the detail select
  `no_meeting_week_id`; drop the stage 1 defaults. The week endpoint loads the week's row (one
  query by `week_start`) with `linkedCount` and `createdBy`.
- Try: edit the reason (every linked report shows it; a leader's own mark doesn't change); a
  leader edits one linked report's reason (unlinked, `linkedCount` − 1) and undo leaves it;
  a leader replaces one with a held report (it's gone from the count); undo (204, the rest are
  gone, the week is back to Due / Upcoming); undo after a group closed (its mark goes too).

## Stage 5: Seed and docs

- `data/seed/small_group_reports.py`: one past week marked church-wide (Spanish reason, e.g.
  "Semana Santa: no hay grupos pequeños"), with one group that met anyway and one that a leader marked
  first, so the week shows all three. Skip the seed's own random skips for that week.
- `docs/ARCHITECTURE.md` (*Small group reports*): the week row, the link, unlinking and undo; the
  role × route table gets the three routes. One line in `CLAUDE.md` next to the no-meeting one.
- Rules 1–13 of the cross-repo spec: fix only what the implementation had to change. Mark this log
  done.

## Not in this spec

- Part of a week, specific groups, or weeks after next.
- Recurring cancellations ("the last week of every month").
- Notifying leaders.
- Marking groups opened later automatically (rule 6: run it again).
