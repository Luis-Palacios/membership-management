# Small group reports: "no meeting" (a date the group didn't meet)

Handoff spec for the membership-management side of **no meeting**: a leader says the group didn't
meet on a date (cancelled, holiday, rain, no meetings the last week of the month…), optionally with
a reason, so that date stops showing as Due / Not filed. It extends small group reports
(`docs/SMALL-GROUP-REPORTS-API-HANDOFF.md`, *rule N* = the cross-repo
`../docs/specs/small-group-reports.md`). The staff-app side is
`staff-app/docs/design/SMALL-GROUP-NO-MEETING.md`; design boards: [Staff App canvas](https://claude.ai/artifact/PLs9gdHVcigkRSAWJrsKs1),
page "Small group reports", row "No meeting".

**Decided (don't re-open):**

- A no meeting is **a `small_group_reports` row with `held = false`**, not a separate table. The
  existing `UNIQUE (small_group_id, meeting_date)` then guarantees a date is a meeting *or* a no
  meeting, never both, and every "is there a report on this date" check (not filed, week status,
  duplicate date) already does the right thing.
- Optional free-text reason, max 255. No categories. Visible to anyone who can view the report
  (it is not pastoral like observations).
- Same rules as a report: today or earlier (rule 2), one per group per date, closed groups refuse
  it (rule 8), only a leader/co-leader of the group on that date can create it (scoped callers),
  edit/delete permissions unchanged.
- A no meeting has **no attendance rows** and null `address` / `group_*` texts.
- A held report can never become a no meeting (protects attendance): the client must delete it
  first. A no meeting **can be replaced** by a held report in one transaction on create
  (`replacesNoMeeting: true`), so abandoning the new report loses nothing.
- Not per-church configurable (no "never meets on the last week" schedule) in this spec.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`small-group-no-meeting`** branch (same name in staff-app). Each stage must pass
`uv run ruff check .` and `uv run ty check`, and be tried against the local API as the roles the
reports handoff lists (admin, elder linked/unlinked, leader in/out of scope, former leader, leader
of a closed group, deacon with no member, user). Keep every convention from the reports handoff
(services/queries/results split, `CamelModel`, domain errors mapped in `_http_error`,
`church_today()`, plain `def` routes, per-route `rate_limit`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration and model | ✅ | see `git log` (stage 1 commit) |
| 2. Create / edit / delete a no meeting, replace on create | ✅ | see `git log` (stage 2 commit) |
| 3. Reads: detail, list, summary, week, roster | ✅ | see `git log` (stage 3 commit) |
| 4. Counting fixes (last report, streaks, filed counts) | ✅ | see `git log` (stage 4 commit) |
| 5. Seed and docs | ✅ | see `git log` (stage 5 commit) |

### Decisions and deviations

- Stage 1: the new fields on the results tuples (`ReportRoster.existing_report_held`,
  `ReportDetail`/`FiledReportRow`/`WeekReportRow` `held` + `not_held_reason`, `RecentMeeting.held`)
  are added **at the end with defaults** (`True`/`None`) so existing constructors and `all_as`
  mappings keep working until stages 2-3 fill them in; drop the defaults if you want them enforced.
- Stage 1 fix: the CHECK `not_held_reason_only_when_not_held` was first written backwards
  (`held OR reason IS NULL`, which rejected every no meeting with a reason). It is now
  `NOT held OR not_held_reason IS NULL`; fixed in its own commit, and the migration was edited in
  place (not yet deployed anywhere).
- Stage 2: Pydantic discriminates the body with a callable `Discriminator` that treats a missing
  `held` as held (a bool literal tag wasn't used). `NotHeldReportBodySchema` forbids extra keys; the
  held body stays lenient, as before.
- Stage 2: `ReportInput` stayed a single tuple with `held`, `not_held_reason` and
  `replaces_no_meeting` (defaults last) instead of a union. `report_id_on_date_query` became
  `report_on_date_query` returning `(id, held)`; `ReportAlreadyExistsError` carries `existing_held`.
- Stage 2 also added `held`/`notHeldReason` to the detail response (create returns it),
  `existingReportHeld` to the duplicate 409 and to the roster response, since those code paths
  were touched anyway; Stage 3 still owns list, summary, week and the roster tests.
- Stage 3: `ReportCounts` is `(all, filed, not_held, not_filed)`; `filed` is held reports only.
  `ReportDate` (from `report_dates_query`, still unfiltered) carries `held`, which feeds
  `RecentMeeting.held`. Week `reports` are sorted held first, no meetings after. `last_report` still
  needs the `held = true` filter: Stage 4.
- Stage 4: only two queries needed the `held = true` filter (`latest_report_ids_query` and the
  `latest_reports` window in `recent_attendance_marks_query`). A grep for `attended_group` and
  `SmallGroupReport` found no other attendance averages or counts; filed counts were done in Stage 3.
- Stage 5: `SKIPPED_WEEK_RATE` went from 0.1 to 0.15 so that, after a third of the skips become no
  meetings (`NO_MEETING_SHARE`), enough weeks stay not filed to show all three states. One reason is
  `None` on purpose (a no meeting without a reason). Rule 13 in the cross-repo spec needed no change.
- Replacing a no meeting flushes the delete before inserting the report (the unit of work inserts
  first and would hit the unique constraint).

## Data model

`small_group_reports` gains:

| Column | Type | Notes |
| --- | --- | --- |
| `held` | `BOOLEAN NOT NULL DEFAULT true` | `server_default=true()` so existing rows are meetings |
| `not_held_reason` | `VARCHAR(255) NULL` | Trimmed; blank → null (`_blank_to_none`) |

Check constraints (named by the convention; hand-write them, autogenerate won't):

- `ck_small_group_reports_not_held_reason_only_when_not_held`: `held = false OR not_held_reason IS NULL`.
- `ck_small_group_reports_not_held_has_no_texts`: `held = true OR (address IS NULL AND
  group_prayer_request IS NULL AND group_praise_report IS NULL AND group_relevant_discussion IS NULL)`.

"No attendance rows when not held" can't be a CHECK (another table); the service enforces it.

Model comment on `held`: *"False = the group didn't meet on meeting_date (a 'no meeting'). It still
occupies the date, so the date isn't 'not filed'; it has no attendance and no group texts."*

## Shapes

### Create body (`POST /small-groups/{id}/reports`) — discriminated on `held`

```jsonc
// held report (unchanged, `held` optional and defaults to true so today's client keeps working)
{ "held": true, "meetingDate": "2026-10-01", "address": "…", "groupPrayerRequest": "…", …,
  "attendances": [ … ], "replacesNoMeeting": false }

// no meeting
{ "held": false, "meetingDate": "2026-09-29", "notHeldReason": "Heavy rain; most of the group couldn’t get there." }
```

- `HeldReportBodySchema` = today's `ReportBodySchema` + `held: Literal[True] = True` +
  `replaces_no_meeting: bool = False` (create only; ignored/rejected on PATCH — 422 if `true`).
- `NotHeldReportBodySchema`: `held: Literal[False]`, `meeting_date`, `not_held_reason: ReportReason = None`
  (`Annotated[str ≤ 255 | None, BeforeValidator(_blank_to_none)]`). Extra keys forbidden.
- Body type: `Annotated[HeldReportBodySchema | NotHeldReportBodySchema, Field(discriminator="held")]`.
  If Pydantic won't discriminate on a bool literal, use a callable `Discriminator` that defaults a
  missing `held` to the held variant; note it in *Decisions*.

### Edit (`PATCH /small-group-reports/{id}`)

- Held report + held body: unchanged behaviour.
- Not-held report + not-held body: replaces `meeting_date` and `not_held_reason` (same date rules;
  duplicate-date check ignores itself). Submitter / submitted_at unchanged.
- Kind mismatch either way: **422** `"A report can't change between a meeting and a no meeting. Delete it and add the other."`
  (`ReportKindChangeError`). The staff app never sends it; it guards against a bad client.

### Delete

Unchanged (`DELETE /small-group-reports/{id}`; closed group → 409).

### Detail (`ReportDetailSchema`)

Add `held: bool` and `not_held_reason: str | None`. For a no meeting: `attendances: []`,
`totals: { roster: 0, attendedGroup: 0, attendedChurch: 0 }` (observations key per rule 9 as today),
`address`/`group_*` null, `observationsVisible` as computed today. `permissions` unchanged.

### List (`GET /small-group-reports`)

- `FiledReportItemSchema` gains `held: bool`, `not_held_reason: str | None` (counts are 0 for a no meeting).
- `status` query param: `all | filed | notHeld | notFiled`. **`filed` = held reports only.**
- `counts`: `{ all, filed, notHeld, notFiled }` (`all = filed + notHeld + notFiled`).
- `q` also matches the reason (fold case/accents like the rest).

### Summary (`GET /small-group-reports/summary`)

- `last_report` = newest **held** report (a no meeting is never a Last report).
- `recent_meetings[]` gains `held: bool | null` (`null` when not filed). `not_filed_dates` unchanged
  (a no meeting has a report id, so it's already excluded).

### Week (`GET /small-group-reports/week`)

- `status` adds `"notHeld"`: no held report in the week but at least one no meeting.
  Precedence: any held report → `submitted`; else any no meeting → `notHeld`; else today's logic.
- `reports[]` items (`WeekReportSchema`) gain `held` and `not_held_reason`; held ones first.

### Roster (`GET /small-groups/{id}/report-roster?date=`)

Add `existing_report_held: bool | null` next to `existing_report_id`, so the date step can show
"Thursday, Oct 1 is marked as no meeting… replace with a report" vs today's duplicate error.

### Duplicate 409

`DuplicateReportHTTPError` body adds `existingReportHeld: bool`:
`{ "detail": "There's already a report…", "existingReportId": 12, "existingReportHeld": false }`.

## Rules (rule 13 in the cross-repo spec, already added; summary)

1. A leader or co-leader of an open group can record that the group didn't meet on a date (today or
   earlier), with an optional reason (≤ 255). It occupies the date like a report.
2. A no-meeting date is never Not filed / Due, and doesn't count toward Needs follow-up (rule 10).
3. It is not a Last report, not Filed in counts, has no attendance and is skipped by missed-meeting
   streaks (rule 11) and attendance figures.
4. Its reason is visible to everyone who can view the group's reports.
5. Creating a held report on a no-meeting date is allowed only with `replacesNoMeeting: true`; the
   no meeting is deleted and the report inserted in one transaction. The reverse is never allowed.

## Errors (new or changed)

| When | HTTP | detail |
| --- | --- | --- |
| Not-held body with `attendances` or group texts | 422 | Pydantic (extra keys forbidden) |
| PATCH changes kind, or `replacesNoMeeting` on PATCH | 422 | "A report can't change between a meeting and a no meeting. Delete it and add the other." |
| Create (either kind) on a date with a report, without a valid replace | 409 | existing duplicate message + `existingReportId` + `existingReportHeld` |
| `replacesNoMeeting: true` but the date's report is **held** | 409 | same duplicate body (`existingReportHeld: true`) — never replace a held report |
| `replacesNoMeeting: true` and no report on the date | — | ignore the flag, create normally |

## Stage 1: Migration and model

- Add the columns and checks to `SmallGroupReport`; `uv run alembic revision --autogenerate -m "add small group report held"`,
  then hand-add both CHECKs and `server_default=sa.true()`. Review; `upgrade head`,
  `downgrade -1`, `upgrade head`; `alembic check` clean.
- Results tuples (`FiledReportRow`, `WeekReportRow`, `ReportDetail`, `RecentMeeting`, roster) gain
  the new fields.

## Stage 2: Create / edit / delete

**Files:** `api/schemas/small_group_reports.py`, `api/routers/small_group_reports.py`,
`data/small_groups/services.py`.

- `ReportInput` becomes a union (`HeldReportInput | NotHeldReportInput`) or gains `held` +
  `not_held_reason`; keep the service the single place that validates.
- `_validated_roster` today runs rules 1, 2, 3, 8 for held reports. Split: a shared
  `_validate_date(small_group, meeting_date, today, ignore_report_id, replaces_no_meeting)`
  (closed → future → duplicate, in that order, as today) and the attendance-roster check for held
  only. A not-held create still runs `NotGroupLeaderOnDateError` for scoped callers.
- Replace path: inside the same session, if the date's report is not held and the flag is set,
  `session.delete(existing)` then insert the held report; one `_commit_report_or_raise_conflict`.
  Lost race → same duplicate error.
- PATCH: load report; kind mismatch → `ReportKindChangeError`. Not-held edit only touches
  `meeting_date` and `not_held_reason`.
- Rate limits: reuse the create/update/delete scopes.

## Stage 3: Reads

- `filed_reports_query` / `week_reports_query`: select `held`, `not_held_reason`.
- `list_reports`: split filed rows into held / not held for `counts` and the `status` filter; `q`
  matches the reason.
- `_week_group`: precedence above (`submitted` only if a held report exists).
- `recent_meetings`: `RecentMeeting(date, report_id, held)` — needs `held` from `report_dates_query`.
- Roster and duplicate error: `existing_report_held`.
- Detail mapping: new fields; for not held, empty attendances and zero totals (no special casing in
  the router beyond that).

## Stage 4: Counting fixes (easy to miss)

Every place that treats "a report" as "a meeting with attendance" must filter `held = true`:

- `latest_report_ids_query` (summary `last_report`, Group detail "Last report").
- `recent_attendance_marks_query`'s inner `latest_reports` (missed streak window): without the
  filter a no meeting eats one of the `MISSED_STREAK_REPORT_WINDOW` slots. The outer join already
  yields no rows for it, so streaks themselves are unaffected (rule 11's "neither break nor extend").
- Any attendance averages or counts added since (grep for `attended_group` and `SmallGroupReport.id`).
- `report_dates_query` stays **unfiltered** on purpose (a no meeting is "filed" for rule 10).

## Stage 5: Seed and docs

- `data/seed/small_group_reports.py` already skips some weeks ("holidays, rain…"). Turn about a third
  of those skips into no meetings with a reason (Spanish, matching the seed's Managua flavour), so
  dashboards show all three states.
- `docs/ARCHITECTURE.md` (*Small group reports*) and one line in `CLAUDE.md`. Rule 13 is already in
  the cross-repo spec; only fix it if the implementation had to differ. Mark this log done.

## Not in this spec

- Per-church schedules ("no meetings the last week of the month") — later as generated no meetings
  or a rule; the column design doesn't block it.
- Marking future dates in advance.
- Reason categories / reporting on reasons.
- "Rescheduled to another day": a report on another weekday already counts for the week but leaves
  the usual day Not filed in Reports (existing gap, unchanged here).
