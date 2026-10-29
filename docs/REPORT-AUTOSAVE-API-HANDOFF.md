# Small group reports: drafts and auto-save (membership-management)

Handoff spec for the membership-management side of **report auto-save**: a report is a `draft` or
`submitted`, a draft is saved on every change (partial attendance allowed), saves carry a
`version` so two writers never overwrite each other, and a draft is invisible to everything but
its group's leaders and the person who started it. *Rule N* = `../docs/specs/report-autosave.md`;
*reports rule N* = `../docs/specs/small-group-reports.md`. The staff-app side is
`staff-app/docs/design/REPORT-AUTOSAVE.md`; design boards: [Staff App canvas](https://claude.ai/artifact/PLs9gdHVcigkRSAWJrsKs1),
page "Report auto-save".

**Decided (don't re-open):**

- A draft is **the same `small_group_reports` row** with `status = 'draft'`, not a separate table.
  The unique `(small_group_id, meeting_date)` keeps doing its job (rule 2), and the attendance and
  items tables don't change shape.
- A save **replaces the whole report** through the existing PATCH (attendance rows and items
  replaced, as today). No field-level endpoints. Conversations anchor to the person or the section
  key, never to a row id, so replacing rows is safe.
- **Optimistic concurrency** with an integer `version`, compared in the `UPDATE … WHERE version = ?`
  (or a `SELECT … FOR UPDATE` and compare). No locks held between requests.
- A no meeting is never a draft.
- Expand/contract: stages 1–5 keep the current staff app working unchanged; stage 6 tightens the
  defaults only after the new staff app is deployed.

Work through it **stage by stage**, one reviewable commit per stage, on the **`report-autosave`**
branch (same name in staff-app). Each stage must pass `uv run ruff check .` and `uv run ty check`,
and be tried against the local API as: admin and elder (linked, unlinked, leading a group or not),
leader and co-leader in scope, leader of another group, former leader, leader of a closed group,
deacon, user. Keep every convention from the reports handoff (services / queries / results split,
`CamelModel`, domain errors mapped in `_http_error`, `church_today()`, plain `def` routes,
per-route `rate_limit`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration and model | ⬜ | |
| 2. Every read ignores drafts | ⬜ | |
| 3. Draft writes: create, save with version, submit, discard, replace, close | ⬜ | |
| 4. Draft reads: detail, roster, list, summary, week | ⬜ | |
| 5. Seed and docs | ⬜ | |
| 6. Contract (after the new staff app is deployed) | ⬜ | |

### Decisions and deviations

- [Anything decided during implementation, and why.]

## Data model

`small_group_reports`:

| Column | Type | Notes |
| --- | --- | --- |
| `status` | `text` not null, default `'submitted'` | CHECK `status IN ('draft', 'submitted')` |
| `submitted_by_member_id` | becomes nullable | CHECK `(status = 'draft') = (submitted_by_member_id IS NULL)` |
| `submitted_at` | becomes nullable, **drop the server default** | CHECK `(status = 'draft') = (submitted_at IS NULL)`; the service sets it on create-as-submitted and on submit |
| `started_by_member_id` | FK `members.id`, not null after backfill, indexed | Backfill = `submitted_by_member_id` |
| `started_at` | `timestamptz` not null, default `now()` | Backfill = `submitted_at` |
| `last_edited_by_member_id` | FK `members.id`, nullable | Null for an unlinked admin's edit |
| `last_edited_at` | `timestamptz`, nullable | Set on every write after the first |
| `version` | `int` not null, default `1` | +1 on every write (save, submit) |

CHECK `held OR status = 'submitted'` (a no meeting is never a draft, rule 1).

`small_group_report_attendances`: `attended_group` and `attended_church` become **nullable**. Keep
the docstring honest: null only while the report is a draft.

A partial index `ON small_group_reports (small_group_id) WHERE status = 'draft'` helps the summary
and list; add it only if a query plan shows the need.

## Visibility (rule 14)

One helper, used by every route below:

```python
def can_see_draft(report: SmallGroupReport, *, caller_member_id: int | None, led_group_ids: frozenset[int]) -> bool
```

True when the caller **currently leads or co-leads** the report's group (`led_small_group_ids_query`
for the caller's member, regardless of role), or when `started_by_member_id == caller_member_id`.
Full roles get **no** blanket access. For a set of groups (list, summary), compute the caller's led
group ids once and filter
`status = 'draft' AND (small_group_id IN led OR started_by_member_id = me)`.

## Shapes

### Create (`POST /small-groups/{id}/reports`)

Held body gains `status: "draft" | "submitted"` (default `"submitted"` until stage 6). With
`"draft"`:

- each attendance row's `attendedGroup` / `attendedChurch` may be `null`;
- the row set must still match the roster for the date (reports rule 3, 422 `attendance`);
- `started_by` = the caller's member (reports rule 5 applies to starting a draft: linked member,
  scoped caller must lead on the date);
- `submitted_*` stay null.

Response: the detail (below), including `id`, `status`, `version`.

No-meeting body gains `replacesDraft: true` (rule 18): allowed only when the date holds a draft the
caller can see; the draft is deleted and the no meeting inserted in one transaction (same
flush-then-insert order as `replacesNoMeeting`).

### Save (`PATCH /small-group-reports/{id}`)

Same body as today plus `version: int` (optional until stage 6). On a **draft**, null answers are
allowed; on a **submitted** report, the body must be complete, as today. Writes go through the
version check:

- `version` given and ≠ current → **409** `"The report changed since you opened it."`, body
  `{ detail, version, lastEditedBy: { memberId, name } | null, lastEditedAt }`.
- otherwise: replace, `version += 1`, `last_edited_by_member_id` = caller's member (may be null),
  `last_edited_at = now()`. `submitted_*` never change (reports rule 6).

A draft the caller can't see is **404** (never 403: it doesn't exist for them).

### Submit (`POST /small-group-reports/{id}/submit`) **new**

Body `{ version }`. In order:

1. 404 if the caller can't see the draft; 409 `already submitted` if it isn't a draft.
2. 409 `closed` if the group is closed (reports rule 8).
3. Version check as on save (409 `changed since`).
4. Reports rule 5 for the **caller** (409 `Link your account to a member`; scoped 422 `didn't lead`).
5. 422 `"The report is incomplete: every person needs both answers."` if any answer is null.
6. `status = 'submitted'`, `submitted_by_member_id` = caller's member, `submitted_at = now()`,
   `version += 1`. Return the detail.

This is the single place the future submit email hooks in (outbox row in the same transaction);
leave a comment there, no email code in this spec.

### Discard (`DELETE /small-group-reports/{id}`)

Unchanged route. A draft: anyone who can see it may delete it (rule 14). Cascades as today.

### Detail (`GET /small-group-reports/{id}`)

Adds `status`, `version`, `startedBy: { memberId, name }`, `startedAt`,
`lastEditedBy: { memberId, name } | null`, `lastEditedAt`. `submittedBy` / `submittedAt` are null
on a draft. Attendance answers may be `null` on a draft. Observations follow reports rule 9.

### Roster (`GET /small-groups/{id}/report-roster?date=`)

`existingReportId` / `existingReportHeld` become one object `existingReport`:

- a draft the caller sees: `{ id, status: "draft", held: true, version }`;
- a draft the caller can't see: `{ status: "draft", startedBy: { name } }` (no id);
- a submitted report or no meeting: `{ id, status: "submitted", held }`.

Keep the two old fields (filled for submitted reports only) until stage 6 so the old client works.

### List (`GET /small-group-reports`)

- **Draft rows** for drafts the caller sees: `kind: "draft"`, `id`, `meetingDate`, `smallGroup`,
  `startedBy`, `answeredCount` (rows with both answers), `rosterCount`, `lastSavedAt`. They sort by
  date with the rest. A new status filter value `status=draft` (counts include it).
- **Not-filed rows** gain `hasDraft: bool` and `draftStartedBy: { name } | null` for drafts the
  caller can't see. They stay not filed (rule 15).
- A draft on **today** (never "not filed", reports rule 10) only appears as a draft row, for the
  people who see it.

### Summary (`GET /small-group-reports/summary`)

Per group in scope: `draft: { id, meetingDate, answeredCount, rosterCount, lastSavedAt } | null`
(the newest draft the caller sees). `lastReport` and the not-filed dates ignore drafts.

### Week (`GET /small-group-reports/week`)

Status computation ignores drafts (a week with only a draft is `notFiled` / `today`, groups
dashboard rule 6). `notFiled` and `today` rows gain `hasDraft: bool`. Full roles see it for every
group (label only, no id).

## Rules (rules 1–21 in the cross-repo spec; the API's share)

- Rule 4: draft rows may have null answers; the set must match the roster.
- Rule 5: submit checks, one-way.
- Rule 9: version on every write.
- Rules 14–17: visibility, 404 for invisible drafts, 409 `draft is in progress` on create when the
  date holds a draft the caller can't see. For a visible draft the existing 409 `already a report`
  + `existingReportId` is returned, and the client opens it.
- Rule 18: `replacesDraft`.
- Rule 19: `close_small_group` deletes the group's drafts in the same transaction and returns how
  many (the close route response gains `discardedDrafts: int`). `GET /small-groups/{id}` gains
  `draftCount` for the close dialog, only for callers who may close the group.

## Errors (new or changed)

| Status | `detail` | When |
| --- | --- | --- |
| 409 | `The report changed since you opened it.` (+ `version`, `lastEditedBy`, `lastEditedAt`) | Version mismatch on save or submit |
| 409 | `A draft is in progress for this date.` (+ `startedBy`) | Create on a date with someone else's draft |
| 409 | `This report is already submitted.` | Submit twice |
| 409 | `Conversations can't start on a draft.` | Any conversation write on a draft |
| 422 | `The report is incomplete: every person needs both answers.` | Submit (or a submitted PATCH) with a null answer |

## Stage 1: Migration and model

- Alembic migration with the columns, CHECKs, backfill and nullable attendance marks above. Write
  the backfill in the migration (`UPDATE … SET started_by_member_id = submitted_by_member_id,
  started_at = submitted_at`), then set not null. Downgrade refuses if any draft exists.
- Model: `ReportStatus` `StrEnum` (`draft`, `submitted`) next to `ReportSection`; new mapped
  columns; `Mapped[bool | None]` on the two attendance marks. Results tuples gain fields at the
  end with defaults (as the no-meeting stage 1 did) so existing constructors keep working.
- `ty` will flag every place that reads `attended_group` as a plain bool: those are exactly the
  places stage 2 must also filter. Fix them by filtering, not by `or False`.

## Stage 2: Every read ignores drafts (rule 16)

Add `SmallGroupReport.status == ReportStatus.SUBMITTED` to every read below (a shared
`submitted_report_condition()` in `queries.py` keeps it greppable). No drafts exist yet, so this
stage changes no output; it is safe to deploy alone.

- `data/small_groups/queries.py`: `filed_reports_query`, `report_dates_query`,
  `latest_report_ids_query`, `week_reports_query`, `shared_reports_query` (Prayer & follow-up),
  `recent_attendance_marks_query` (streaks, reports rule 11), `guests_last_attended_query`,
  `latest_guest_report_date_query`, and the item / tagged-people reads that serve lists and
  timelines.
- `data/guests/queries.py`: `_last_attended`, `guest_rows_query`.
- `data/small_groups/conversation_queries.py`: inbox, counts, needs-reply (a draft has no
  conversations, but keep the filter so it never leaks).
- The person timeline and Recent activity reads (members and guests), wherever the
  `person-timeline` work put them.
- `report_on_date_query` and `report_in_scope_query` are **not** filtered: they find drafts on
  purpose (duplicate date, detail). Their callers apply the visibility helper in stages 3–4.

Check: insert one draft by hand in a scratch DB and confirm no endpoint above shows it.

## Stage 3: Draft writes

- `create_report(..., status)`: drafts allow null answers (`_validated_roster` gets an
  `allow_unanswered` flag); `started_by_member_id` = caller; `submitted_*` only when submitted.
- Duplicate date: an existing draft the caller can't see → the new 409; one they can see → the
  existing 409 with `existingReportId`.
- `update_report(..., version)`: version check, `last_edited_*`, `version += 1`; draft vs submitted
  completeness.
- `submit_report(session, report, *, version, caller_member_id, caller_is_scoped, today)` and the
  route.
- DELETE: draft visibility for drafts.
- `replacesDraft` on the no-meeting create.
- `close_small_group`: delete drafts, return the count; route response and `draftCount` on group
  detail.
- Conversation writes on a draft: 409.

## Stage 4: Draft reads

Detail fields, roster `existingReport`, list draft rows and `hasDraft`, `status=draft` filter and
counts, summary `draft`, week `hasDraft`, all as in Shapes. staff-app's types in
`api/small-groups-api` are written by hand from these shapes; list every changed schema in the
commit message so that session can follow it.

## Stage 5: Seed and docs

- Seed: one draft for Jóvenes Bello Horizonte on its most recent meeting day (attendance taken
  live: everyone's group answer, church for 5 of 8, no sections), and one draft on a past
  not-filed date of another group, started by its leader. Re-running the seed stays idempotent.
- `docs/ARCHITECTURE.md`: a short "Report status and drafts" section pointing at the spec.
- Update the reports handoff's notes where they say a report is always complete.

## Stage 6: Contract (only after the new staff app is deployed)

- `version` required on PATCH and submit (422 without it).
- Create default `status` becomes `draft`.
- Drop `existingReportId` / `existingReportHeld` from the roster response.
- Tell staff-app which types changed (`api/small-groups-api`).

## Not in this spec

- The submit email (later, an outbox row in `submit_report`).
- Field-level PATCH, live presence, report edit history.
- Expiring old drafts.
