# Report conversations Part 1b: the Unread tab and *Mark all read*

Handoff spec for the membership-management side of **Part 1b** of report conversations. Read the
cross-repo spec first: `../docs/specs/report-conversations.md` (workspace folder
`members-management/docs/specs/`), above all **rule 17**, plus rules 11 (unread) and 12 (needs my
reply); its rules are referred to as *rule N*. It builds on `docs/REPORT-CONVERSATIONS-API-HANDOFF.md`
and `docs/PRAYER-FOLLOW-UP-API-HANDOFF.md` (both on `main`): the inbox, the read rows and the anchors
are unchanged.

Three pieces of work, in-app only:

- **Stage 1: `tab=unread`** on `GET /report-conversations` and an `unread` tab count, both filtered
  in SQL. No migration.
- **Stage 2: `report_conversations.last_activity_at`**, migration with backfill, set on every new
  comment and never moved back.
- **Stage 3: `POST /report-conversations/read-all?smallGroupId=`** (*Mark all read*).

> **Email stays out.** `last_activity_at` exists for Part 2's throttle as well, but nothing here
> writes outbox rows, calls auth-server or starts `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`.
> Part 1b runs as usual (not learning mode).

Work through it **stage by stage**, one reviewable commit per stage, on the **`unread-tab`** branch.
Each stage must pass `uv run ruff check .` and `uv run ty check` (and `uv run alembic check` from
stage 2 on), and be tried against the local API (`TestClient` with `get_current_claims` overridden,
against a scratch database, never the dev one) as each role: `admin`, `elder` (linked and
unlinked), `smallGroupLeader` (in and out of scope, former leader), `deacon` with no member,
`user`. There's no test runner yet, so note in *Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `conversation_services.py` directly,
`conversation_queries.py` builds `Select`s, `results.py` holds `NamedTuple`s, schemas are
`CamelModel`, and routes doing blocking database work stay plain `def`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. `tab=unread` and its count | ✅ | `1342a40` |
| 2. `last_activity_at` migration and backfill | ✅ | `9bd077b` |
| 3. `POST /report-conversations/read-all`, docs | ✅ | this commit |

### Decisions and deviations

- **How it was tried:** no test runner, so a throwaway `TestClient` script (not committed) with
  `get_current_claims` overridden per role, against a scratch Postgres database (`unread-scratch`:
  migrated, seeded, then fixtures: members 33, 49, 54, 41, 27 linked to the seed's made-up user ids,
  group 3 closed with its leaders' periods ended on the close date, member 27 stepped down as
  group 2's co-leader). The dev database was not touched. Roles: admin (unlinked), elder linked
  (m33, author of the seed's elder comments) and unlinked, leader of group 2 (m49), leader of group
  5 (m54, out of scope for 2), leader of the closed group 3 (m41), former leader (m27), deacon with
  no member, `user`.
- **Stage 1:** the unread condition is `_unread(read, user_id)` in `conversation_queries.py`, with
  the caller's read row outer-joined as `caller_read` (`_join_caller_read`). The tab filter, total
  and page share one `_tab_threads` `FROM`/`WHERE` builder (the total and the page used to repeat
  it), so they can't drift; the page query keeps its own read join for the row's `last_read_at`.
  The count is a fourth `FILTER` in `inbox_counts_query`, which now takes the user id. Tried: every
  role's inbox responses (4 tabs × no filter / `smallGroupId=2`, plus `/counts`) dumped on `main`
  and on this branch: the 63 that `main` answers are identical once `counts.unread` is removed, and
  `tab=unread` (422 on `main`) answers 200 (403 for `user`). For every role each tab's `total` equals
  its count, every *Unread* row has `unread: true`, the open + resolved rows flagged `unread` are
  exactly the *Unread* tab, and paging with `limit=2` returns each thread once. Admin and unlinked
  elder see all 10 unread (no read rows, none of the comments are theirs), the linked elder 7 (their
  own newest comments are not unread), resolved threads included; leader g2 1; leaders g5 and
  closed g3 0 (the newest comment is theirs); former leader and deacon 0; `user` 403. Marking g2's
  unread thread read dropped the count by one and took it off the tab; a comment by the elder put
  it back for the leader and not for the elder.
- **Stage 2:** migration `096025ed70a6`. Autogenerate found only the column (as NOT NULL, which
  would fail on existing rows); the nullable add, the backfill and `SET NOT NULL` are hand-written.
  Set in `_get_or_create` and `add_comment` next to `last_comment_at`; `_sync_last_comment` (delete)
  and `edit_comment` don't touch it; the seed sets it to the newest comment, deleted or not. Tried:
  `alembic check` clean; `downgrade -1` + `upgrade head` round-trip on the scratch DB, where thread 7
  first had its newest comment soft-deleted (as `delete_comment` would): after the backfill it is
  the only thread with `last_activity_at > last_comment_at`, the other nine have them equal, and
  all ten match `max(created_at)` of their comments. Every role's inbox dump (stage 1 code on the
  downgraded DB vs this branch on the upgraded one) is byte-identical. Through the API: a new thread
  gets the comment's time in both columns; a reply moves both; an edit moves neither; deleting that
  reply moves `last_comment_at` back and leaves `last_activity_at`. The seed run on a fresh
  migrated DB sets it on all 10 threads to their newest comment.
- **Stage 3:** `mark_all_read_query` is one statement: a `target` CTE (the audience's threads with
  their `last_activity_at` and the stage 1 unread flag), the upsert as a data-modifying CTE
  (`ON CONFLICT … greatest(…)`, with `WHERE last_read_at < excluded` so rows already at or past it
  aren't rewritten), and the count over `target`'s flag. Both CTEs see one snapshot, so `marked`
  can't disagree with the write. Rate limit `30/minute` on top of the default. The route returns
  `MarkAllReadSchema`. Tried: elder (linked) with `smallGroupId=2` marked 2, group 2's unread went
  to 0 and the other groups' five unread threads stayed; leader g2 with `smallGroupId=1` (outside
  the audience) got `{ "marked": 0 }` and no read row changed; then for every role `marked` equalled
  the unread count before, the count was 0 after, and a second call marked 0 (admin 10, elder
  linked 5, elder unlinked 11, leaders/former leader/deacon 0, `user` 403). Admin's read row on
  thread 1, set a day ahead beforehand, kept its later value (`greatest`); thread 7 (newest comment
  deleted) got `last_read_at = last_activity_at`, past `last_comment_at`; admin ended with a row for
  all 11 threads. A comment by the elder afterwards made thread 2 unread again for admin and leader
  g2; leader g5's call left leader g2's unread alone and leader g2's marked exactly 1 without
  touching admin's. Mid-click: with a comment's transaction open (thread row locked, comment and
  `last_*` written, not committed) admin's read-all returned at once with `marked: 0`, and once the
  comment committed thread 2 was unread for admin.
- **For the staff app (stage 2b):** `InboxCountsSchema.unread`, `tab=unread`, and
  `POST /report-conversations/read-all` → `MarkAllReadSchema { marked }` are new; regenerate the API
  types. Deploys need the migration (`096025ed70a6`) before the service update, as usual.

## Who can do what

No new permission (rule 4): both routes are the inbox's.

| Role | `GET /report-conversations?tab=unread` | `POST /report-conversations/read-all` |
| --- | --- | --- |
| admin, elder (linked or not) | every group's threads unread for them | marks every group's threads (or the filtered group's) |
| smallGroupLeader, deacon (leading) | the threads of groups in scope | the same threads |
| former leader | the closed groups they co-led when it closed | the same threads |
| deacon with no member | empty, counts 0 | `{ "marked": 0 }` |
| user | 403 (`smallGroupReports: view`) | 403 |

Reading and marking read need **no linked member** (rule 5 is about comments): the read rows are
keyed on the JWT `sub`. A `smallGroupId` outside the caller's audience behaves like the inbox: an
empty page, and `{ "marked": 0 }` here (no 404, which would say the group exists).

## Stage 1: `tab=unread` and its count

**Unread in SQL** (rule 11, rule 17): a thread is unread for the caller when
`last_comment_user_id <> :sub AND (read.last_read_at IS NULL OR read.last_read_at < last_comment_at)`,
with `read` the caller's `report_conversation_reads` row (outer join on `conversation_id` **and**
`user_id = :sub`). One helper in `conversation_queries.py` builds this condition and the outer join,
used by the count, the total and the page query; it is the SQL twin of the Python `is_unread`, which
stays for the row flags. So for every row of the *Unread* tab `unread` is `true`, and paging, totals
and counts agree.

**Tab:** `InboxTab` gains `"unread"`. Any status (open and resolved). Order as every tab: newest
activity first (`last_comment_at DESC, id DESC`).

**Count:** `counts.unread` added to the one `COUNT(*) FILTER` pass (`inbox_counts_query` gains the
user id and the read join). Like the other counts it ignores `smallGroupId`. The sidebar badge
(`GET /report-conversations/counts`) and the dashboard blocks (`tab=reply`) **don't change**
(rule 17: the badge keeps meaning "someone is waiting on us").

**Shape:** `InboxCountsSchema` / `InboxCounts` get `unread: int` (additive: the staff app regenerates
its API types).

**Try:** for each role, every tab's `total` equals the matching count with no group filter; every
*Unread* row has `unread: true`, and the rows of the other tabs that have `unread: true` are exactly
the *Unread* rows; paging through *Unread* (`limit=2`) gives each thread once; a thread whose newest
comment is the caller's own isn't unread; `POST …/{id}/read` takes it off the tab and the count
drops by one; a reply by someone else brings it back; a resolved thread can be unread.

## Stage 2: `last_activity_at` migration and backfill

**Column:** `report_conversations.last_activity_at TIMESTAMPTZ NOT NULL`: the newest comment's
`created_at` **counting deleted ones** (rule 17). Unlike `last_comment_at`, deleting a comment never
moves it back.

**Migration** (autogenerate, then edit): add the column nullable, backfill, then `SET NOT NULL`:
`last_activity_at = coalesce((SELECT max(created_at) FROM report_conversation_comments WHERE
conversation_id = report_conversations.id), last_comment_at)` (the fallback is for a thread with no
comment rows, which the code never creates). No server default: every insert sets it. No index
(stage 3 filters through the report's group, like the inbox). The downgrade drops the column.

**Writes:** `_get_or_create` sets it with `last_comment_at`; `add_comment` sets it to the comment's
time (under the thread lock, as `last_comment_at`); `delete_comment` / `_sync_last_comment` leave it
alone; editing doesn't touch it. The seed sets it to the newest comment's `created_at`, deleted or
not.

**Try:** `alembic check` clean; `downgrade -1` + `upgrade head` round-trip on the scratch DB; after
the backfill, a thread whose newest comment is deleted has `last_activity_at > last_comment_at` and
every other thread has them equal; adding a comment moves both; deleting the newest moves only
`last_comment_at`; the inbox responses for every role are identical before and after.

## Stage 3: `POST /report-conversations/read-all`, docs

**Route:** `POST /report-conversations/read-all?smallGroupId=` (declared before any
`/report-conversations/{id}` route that could match it), dependencies `_needs_reports_view`, the
default rate limit plus `rate_limit("30/minute", scope="mark_all_report_conversations_read")`,
`SmallGroupScopeDep`. The audience is `conversation_group_ids(claims, scope)`, as the inbox.

**What it marks** (rule 17): every thread in the caller's view (submitted reports in the audience,
any status) and in `smallGroupId` when set, **not only the unread ones**, up to that thread's
`last_activity_at`, never `now()`:

```sql
INSERT INTO report_conversation_reads (user_id, conversation_id, last_read_at)
SELECT :sub, c.id, c.last_activity_at FROM report_conversations c JOIN small_group_reports r … WHERE …
ON CONFLICT (user_id, conversation_id)
DO UPDATE SET last_read_at = greatest(report_conversation_reads.last_read_at, excluded.last_read_at)
```

One statement, in one transaction. Threads whose newest comment was deleted are marked past it too
(Part 2's throttle and its hand-check depend on that), though they weren't unread. A comment that
commits while this runs keeps a later `last_activity_at` than the mark, so it stays unread.

**Response:** `{ "marked": n }` (`MarkAllReadSchema`), `n` = the threads that **were unread** for the
caller (stage 1's condition) and no longer are: what the user sees leave the tab, so the staff app
can say "N marked read". Computed in the same statement (the upsert as a data-modifying CTE, the
count over the target rows' unread flag), so it can't disagree with the write.

**Try:** per role, `marked` equals the `unread` count just before (no filter) and the count is 0
after; with `smallGroupId`, only that group's threads are marked and other groups' stay unread; a
group outside the audience gives `{ "marked": 0 }` and changes nothing; calling it twice gives 0 the
second time; a thread with a read mark later than `last_activity_at` (read after a deleted comment)
keeps its mark (`greatest`); a thread whose newest comment was deleted gets `last_read_at =
last_activity_at`; a comment added afterwards by someone else makes the thread unread again; `user`
403; deacon with no member `{ "marked": 0 }`.

**Docs:** `docs/ARCHITECTURE.md` (*Report conversations*: unread tab, `last_activity_at`,
read-all), the inbox line in `CLAUDE.md`, and this log.

## Not in this spec

- The staff app's *Unread* tab and button (`staff-app`, stage 2b).
- Email, the outbox and the throttle that also reads `last_activity_at` (Part 2).
- Changing the sidebar badge or the dashboard blocks (rule 17 keeps them *Needs my reply* only).
- Ordering the inbox by `last_activity_at` (it stays `last_comment_at`).
