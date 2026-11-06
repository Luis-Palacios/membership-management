# Report conversations Part 1d: the Resolved tab's period filter

Handoff spec for the membership-management side of **Part 1d** of report conversations. Read the
cross-repo spec first: `../docs/specs/report-conversations.md` (workspace folder
`members-management/docs/specs/`), above all **rule 15** (its *Changed Nov 6, 2026 (Part 1d)*
paragraph) and the inbox row of *Contracts (Part 1)*; its rules are referred to as *rule N*. It
builds on `docs/UNREAD-DOT-API-HANDOFF.md` (done, on `main`): counts, *Unread*, *Mark all read* and
the badge are unchanged.

**Status: in progress.** No migration.

One piece of work, in-app only:

- **Stage 1: `resolvedSince`** on `GET /report-conversations`, only with `tab=resolved`.
- **Stage 2: docs** (`docs/ARCHITECTURE.md`, `CLAUDE.md`, this log).

> **Email stays out.** Nothing here writes outbox rows, calls auth-server or starts
> `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`. Part 1d runs as usual (not learning mode).

Work through it **stage by stage**, one reviewable commit per stage, on the **`resolved-period`**
branch. Each stage must pass `uv run ruff check .` and `uv run ty check`, and be tried against the
local API (`TestClient` with `get_current_claims` overridden, against a scratch database, never the
dev one) as each role: `admin`, `elder`, `smallGroupLeader` (in and out of scope), `user`. There's
no test runner yet, so note in *Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `conversation_services.py` directly,
`conversation_queries.py` builds `Select`s, schemas are `CamelModel`, and routes doing blocking
database work stay plain `def`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. `resolvedSince` on `/report-conversations` | ⬜ | |
| 2. Docs | ⬜ | |

### Decisions and deviations

(Filled in as the stages land.)

## Who can do what

No new permission (rule 4), no change to the audience: the filter only narrows the *Resolved* tab
of whatever the caller already sees.

## Stage 1: `resolvedSince` on `/report-conversations`

**Shape:** a new optional query parameter `resolvedSince`, an ISO 8601 instant **with an offset**
(`2026-10-07T14:30:00Z`, `2026-01-01T00:00:00-06:00`). Typed as pydantic's `AwareDatetime`, so a
naive value (or garbage) is FastAPI's own 422. The staff app computes it (*Last 30 days*, *Last 3
months*, *This year* in `CHURCH_TIMEZONE`); this API knows nothing about periods.

- Only with `tab=resolved`: any other tab with `resolvedSince` set is **422** `resolvedSince only
  applies to the resolved tab.` (not silently ignored, so a staff-app bug shows up).
- Keeps threads with `resolved_at >= resolvedSince`. Added to `_tab_threads`, so `total` and the
  page's rows agree (same `FROM`/`WHERE`), and "Show more" (`offset`) with the same instant pages
  the same set.
- **`counts` never take it** (rule 15: the tab count stays all time), like they never take
  `smallGroupId`.
- Combines with `smallGroupId` (both filters apply).
- Order unchanged: `last_comment_at desc, id desc`.

**Index:** none added. The resolved set per caller is small (hundreds, then low thousands over
years), the existing `last_comment_at desc` index drives the order, and `resolved_at` is a cheap
filter on the rows the audience join already reads. Revisit with `EXPLAIN` if the table grows past
tens of thousands.

**Try:** per role, `tab=resolved` without the parameter is identical to `main` (items, total,
counts); with `resolvedSince` in the future → 0 rows, `total: 0`, `counts.resolved` unchanged; far
in the past → same as without; a cut in the middle → only threads resolved at or after it, `total`
matches, and paging with `limit=1&offset=n` walks exactly `total` rows; with `smallGroupId` both
apply; a naive datetime, garbage, or `tab=open&resolvedSince=…` → 422; reopening a thread drops it
from the filtered list (`resolved_at` cleared), resolving it again brings it back with the new
time; `user` → 403 as today.

## Stage 2: docs

`docs/ARCHITECTURE.md` (*Report conversations*, inbox paragraph), the conversations line in
`CLAUDE.md`, and this log.

## Not in this spec

- The select, `?period=`, the count line and the empty state (`staff-app`, step 2d).
- Changing the tab counts, the order, or the other tabs.
- Email, the outbox and the throttle (Part 2).
