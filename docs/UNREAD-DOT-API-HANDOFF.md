# Report conversations Part 1c: the unread dot

Handoff spec for the membership-management side of **Part 1c** of report conversations. Read the
cross-repo spec first: `../docs/specs/report-conversations.md` (workspace folder
`members-management/docs/specs/`), above all **rule 17** (its *Changed Nov 5, 2026 (Part 1c)*
paragraph), plus rules 11 (unread) and 12 (needs my reply); its rules are referred to as *rule N*.
It builds on `docs/UNREAD-TAB-API-HANDOFF.md` (done, on `main`): the unread condition, the inbox and
*Mark all read* are unchanged.

**Status: in progress.** The staff-app side (spec step 2c, the dot itself) comes after, in
`staff-app/docs/design/UNREAD-DOT.md`.

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
| 1. `hasUnread` on `/report-conversations/counts` | ⬜ | |
| 2. Docs | ⬜ | |

### Decisions and deviations

- (none yet)

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
else turns it back on; a group filter isn't accepted (the route takes none); `user` and deacon with
no member get `{ needsMyReply: 0, hasUnread: false }`, 200.

## Stage 2: docs

`docs/ARCHITECTURE.md` (*Report conversations*, inbox paragraph, and the *Permissions* table's
`/report-conversations/counts` row), the inbox line in `CLAUDE.md`, and this log.

## Not in this spec

- The dot, its hiding when the gold number shows, and the screen-reader label (`staff-app`, step 2c).
- Email, the outbox and the throttle (Part 2).
- Changing the dashboard blocks or the gold number (rule 17 keeps them *Needs my reply* only).
