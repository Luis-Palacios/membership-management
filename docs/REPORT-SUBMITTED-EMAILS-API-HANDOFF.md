# Report submitted emails (membership-management)

Handoff for the API side of **report submitted emails**: submitting a report writes one
`small_group_report.submitted` outbox row; the Part 2 worker turns it into `report.submitted`
emails to the group's watchers (category `report_submitted`), and the preferences routes get one
switch per kind of email. Outbox, claiming, sending and watching are Part 2's, reused as built.

- Rules and contracts: `../docs/specs/report-submitted-emails.md` (*rule N*), step 2 and
  *Contracts → membership-management*.
- Extends `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md` and `docs/ARCHITECTURE.md`,
  *Report conversations, Part 2*.
- auth-server: `../auth-server/docs/REPORT-SUBMITTED-EMAILS-HANDOFF.md` (merged, PR #36). staff-app:
  `../staff-app/docs/design/REPORT-SUBMITTED-EMAILS.md` (uses Stage 3's preferences shape).

Branch **`feature/report-submitted-emails`**. Each stage: `uv run ruff check .`, `uv run ty check`,
`uv run alembic check`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Kill switch; the event in both submit transactions | ✅ | `a700042` |
| 2. Consumer, dispatch by event type, worker on either switch, fast path on submit | ✅ | `af49baa` |
| 3. Preferences contract (`email` / `available`); docs | ✅ | `ad4ec07` |
| Handoff written | ✅ | (this commit) |

## Decisions and deviations

- No migration: event type, delivery category and preference category are plain strings
  (`alembic check` clean).
- `create_report` / `submit_report` return `(report, event_id | None)`, like `add_comment`, so the
  routes can queue the fast path. `create_report` writes the event inside
  `_commit_report_or_raise_conflict`'s `try` (it needs a flush for the report id, and that flush is
  where a lost (group, date) race shows), so the race still maps to the usual 409.
- `occurredAt` / `created_at` = the report's `submitted_at`, read back after the flush (the column
  is set to `now()`). Head start (`HEAD_START`, now public) and 24 h deadline shared with comments.
- The consumer reuses `readers_of_group` (rule 23) and `watch_opt_out_user_ids_query`; nothing copied.
  Candidates = possible watchers minus the submitter's linked user; leaders are never possible
  watchers (`smallGroups:all`), so rule 7 needs no extra check. A report gone, not submitted or
  without a submitter → processed, no deliveries. `attendedCount`/`peopleCount` only when `held`.
- `worker/events.py`: `_KNOWN` maps `event_type` → `_Consumer(schema_version, candidates, process)`.
  Worker log lines say "emails" / "email worker" now (both kinds).
- Preferences `PUT`: `{ email: {} }` is a 200 no-op; missing `email`, null values and unknown keys
  (nested or top-level) are 422. Bools stay pydantic-lax like every other schema here.
- The watch routes never had a kill-switch gate, so "available while either switch is on" holds
  with no change.
- No test suite exists; as in Part 2, checks were scratch scripts against the local DB inside one
  rolled-back transaction (fake permissions lookup and Sender: no network, no email): which writes add
  an event (both submit paths yes; draft, save, edit, delete, church-wide week, switch off no); the
  event's shape; recipients (submitter, opted-out, non-reader, missing perms and the leader
  excluded); held vs not-held payloads; deleted report; per-category preference; head start; unknown
  type → dead; and the routes through `TestClient` (preferences GET/PUT shapes and 422s, fast path
  queued from both submit routes, nothing queued with the switch off).
- PR #73 review: `set_enabled` no longer commits; `PUT /me/notification-preferences` commits once
  after every key, so a request changing both switches is one transaction.
- Production: turn on `REPORT_SUBMITTED_EMAILS_ENABLED` only once auth-server's `report.submitted`
  template is deployed.
