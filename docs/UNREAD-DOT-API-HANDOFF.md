# Report conversations Part 1c: the unread dot

Handoff spec for the membership-management side of **Part 1c** of report conversations. Read the
cross-repo spec first: `../docs/specs/report-conversations.md` (workspace folder
`members-management/docs/specs/`), above all **rule 17** (its *Changed Nov 5, 2026 (Part 1c)*
paragraph), plus rules 11 (unread) and 12 (needs my reply); its rules are referred to as *rule N*.
It builds on `docs/UNREAD-TAB-API-HANDOFF.md` (done, on `main`): the unread condition, the inbox and
*Mark all read* are unchanged.

**Status: done** (2026-11-05). Stages 1–2 are merged to `main` (PR #69, rebased: stage 2 is
`a8cfd2d`). No migration. The staff-app side (spec step 2c, the dot itself) is next, in
`staff-app/docs/design/UNREAD-DOT.md`. The stage sections below are kept as the record of how it was
built; the code is the reference for the current shapes.

One piece of work, in-app only:

- **Stage 1: `hasUnread`** on `GET /report-conversations/counts`, an `EXISTS` over the *Unread*
  tab's SQL, no group filter. No migration.
- **Stage 2: docs** (`docs/ARCHITECTURE.md`, `CLAUDE.md`, this log).

> **Email stays out.** Nothing here writes outbox rows, calls auth-server or starts
> `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`. Part 1c runs as usual (not learning mode).

Work through it **stage by stage**, one reviewable commit per stage, on the **`unread-dot`** branch.
Each stage must pass `uv run ruff check .` and `uv run ty check`, and be tried against the local API
(`TestClient` with `get_current_claims` overridden, against a scratch database, never the dev one)
as each role: `admin`, `elder` (linked and unlinked), `smallGroupLeader` (in and out of scope,
former leader), `deacon` with no member, `user`. There's no test runner yet, so note in *Decisions
and deviations* what you tried and how.

Keep the existing conventions: routes call `conversation_services.py` directly,
`conversation_queries.py` builds `Select`s, `results.py` holds `NamedTuple`s, schemas are
`CamelModel`, and routes doing blocking database work stay plain `def`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. `hasUnread` on `/report-conversations/counts` | ✅ | `55460ce` |
| 2. Docs | ✅ | `a8cfd2d` |

### Decisions and deviations

- **How it was tried:** no test runner, so a throwaway `TestClient` script (not committed) with
  `get_current_claims` overridden per role, against a scratch Postgres database (`udot-scratch`:
  migrated, seeded, then the Part 1b fixtures: members 33, 49, 54, 41, 27 linked to the seed's
  made-up user ids, group 3 closed with its leaders' periods ended on the close date, member 27
  stepped down as group 2's co-leader), reset and re-seeded before each run. The dev database was
  not touched. Roles: admin (unlinked), elder linked (m33, author of the seed's elder comments) and
  unlinked, leader of group 2 (m49), leader of group 5 (m54, outside group 2's audience), leader of
  the closed group 3 (m41), former leader (m27), deacon with no member, `user`.
- **Stage 1:** `badge_query` in `conversation_queries.py` replaces `needs_reply_count_query`: one
  `SELECT` of the unchanged `reply` count as a scalar subquery and `EXISTS (_tab_threads(…,
  "unread", None))`, so the dot reads the *Unread* tab's own `FROM`/`WHERE` (the caller's read row
  outer-joined, the audience filters) and nothing else. `get_badge` (was `count_needing_reply`)
  returns a `ConversationBadge` and still answers `(0, false)` for an empty audience without a
  query; `NeedsMyReplyCountSchema` became `ConversationBadgeSchema`. Tried: `needsMyReply` for every
  role is identical to `main` (a `main` worktree against the same DB: admin and both elders 4,
  leader g2 1, everyone else 0). After every step below, for every role, `hasUnread` equalled
  `counts.unread > 0` from `GET /report-conversations?tab=unread` and `needsMyReply` equalled
  `counts.reply` (41 checks, all passed). Unread and not: leader g2's only unread thread (7, an
  elder's comment) turned the dot on; `POST …/7/read` turned it off with `needsMyReply` still 1; an
  elder's reply on thread 2 turned it back on for leader g2 and left leader g5 (outside group 2)
  off. *Mark all read*: every role's `hasUnread` was `false` right after (admin marked 10, elder
  linked 6, elder unlinked 10, leader g2 1, the others 0, `user` 403 on read-all and still 200
  `{0, false}` on counts). The dot-only state: once the linked elder answered every thread waiting
  on elders, admin and the unlinked elder had `needsMyReply: 0, hasUnread: true`, the linked elder
  (author) `0, false`, the leaders of groups 2, 5 and the closed 3 the elder's replies unread.
  Newest comment deleted: leader g5 replied twice on thread 5 after admin and both elders had
  marked all read; the second reply made it unread for them; deleting it (newest live comment now
  the first, already read) turned the dot off for all three, `needsMyReply` unchanged. The same on
  thread 2 the other way round (an elder's unread comment deleted, leader g2's dot off), and a new
  reply afterwards turned it back on. Former leader, deacon with no member and `user` were
  `{ needsMyReply: 0, hasUnread: false }`, 200, throughout. `?smallGroupId=1` on the counts route is
  ignored (same answer as without it).
- **Stage 2:** docs only: `docs/ARCHITECTURE.md` (*Permissions* row for the counts route, *Report
  conversations* inbox paragraph), the conversations line in `CLAUDE.md`.
- **For the staff app (step 2c):** `GET /report-conversations/counts` now returns
  `{ needsMyReply, hasUnread }`, schema `ConversationBadgeSchema` (was `NeedsMyReplyCountSchema`);
  regenerate the API types. No migration, no new permission.

## Who can do what

No new permission (rule 4), and the route keeps its rules: no permission needed, 0 / `false` outside
the audience instead of 403 (the badge is fetched on every page, for every role).

| Role | `needsMyReply` | `hasUnread` |
| --- | --- | --- |
| admin, elder (linked or not) | threads on every group waiting for the elders' side | any thread in any group unread for them |
| smallGroupLeader, deacon (leading) | threads in scope waiting for the leaders' side | any thread in scope unread for them |
| former leader | the closed groups they co-led when it closed | the same threads |
| deacon with no member, user | 0 | `false` |

Like the *Unread* tab, `hasUnread` needs **no linked member**: the read rows are keyed on the JWT
`sub`.

## Stage 1: `hasUnread` on `/report-conversations/counts`

**Shape:** the response becomes `{ needsMyReply: int, hasUnread: bool }` (additive; the staff app
regenerates its API types). The schema `NeedsMyReplyCountSchema` is renamed to say what it now holds
(`ConversationBadgeSchema`); its OpenAPI component name changes with it (the staff app doesn't
refer to `NeedsMyReplyCountSchema` by name today, so only the regeneration picks it up).

**Unread in SQL** (rule 17): `hasUnread` is
`EXISTS (the Unread tab's threads in the caller's audience)`, built from the same `_tab_threads(…,
tab="unread", small_group_id=None)` the inbox total and page use, so the dot and the tab can't
disagree: `hasUnread` is true exactly when the inbox's `counts.unread` (which ignores `smallGroupId`)
is above 0. An `EXISTS`, not a count: it stops at the first unread thread, since the dot has no
number. Like the count, any status (a resolved thread can be unread), and a thread whose newest live
comment is the caller's own, or whose newer comment was deleted, isn't unread.

**One round trip:** the route runs once per page render, so `needsMyReply` (the existing
`needs_reply_count_query` as a scalar subquery) and `hasUnread` are two columns of one `SELECT`.
An empty audience (`conversation_group_ids` is an empty set) answers `(0, false)` without a query,
as today.

**Unchanged:** the dashboard blocks (`tab=reply`), the inbox counts, *Mark all read* and the meaning
of the gold number (rule 17: one signal at a time is the staff app's job, the API returns both).

**Try:** per role, `hasUnread` equals `GET /report-conversations` → `counts.unread > 0`, and
`needsMyReply` is what it was on `main`; unread and not (a thread unread for the caller turns it
on, reading it turns it off when it was the only one); after `POST /report-conversations/read-all`
it is `false`; a thread whose newest comment (by someone else, unread) is deleted, leaving the
caller's own or an already-read comment as the newest live one, turns it off; a reply by someone
else turns it back on; a `smallGroupId` on the URL is ignored (the route takes none); `user` and deacon with
no member get `{ needsMyReply: 0, hasUnread: false }`, 200.

## Stage 2: docs

`docs/ARCHITECTURE.md` (*Report conversations*, inbox paragraph, and the *Permissions* table's
`/report-conversations/counts` row), the inbox line in `CLAUDE.md`, and this log.

## Not in this spec

- The dot, its hiding when the gold number shows, and the screen-reader label (`staff-app`, step 2c).
- Email, the outbox and the throttle (Part 2).
- Changing the dashboard blocks or the gold number (rule 17 keeps them *Needs my reply* only).
