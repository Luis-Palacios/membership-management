# Report conversations, Part 2: email notifications (membership-management)

> **Read first (added Oct 2026):** this Part 2 handoff was written before section threads.
> **Prayer & follow-up** (`docs/specs/prayer-follow-up.md`) ships first and adds conversations about a
> report section (prayer, praise, follow-up), not only about a person. Before starting Part 2, apply
> that spec's *Changes for report conversations Part 2* here (stage 2: `path` with `?section=` and the `topic` field). Part 2 still comes next,
> slowly, one change at a time, as described below.

Handoff spec for the API side of **conversation emails**: a transactional outbox written in the same
transaction as the comment, a fast path with FastAPI `BackgroundTasks`, a sweeper loop that retries,
and the opt-out. Cross-repo rules: `../docs/specs/report-conversations.md` (*Contracts (Part 2:
email)*). The sender is auth-server: `auth-server/docs/REPORT-CONVERSATIONS-EMAIL-HANDOFF.md` (its
Stage 3 must exist before this Stage 4 can send anything). Part 1 is `docs/REPORT-CONVERSATIONS-API-HANDOFF.md`.

> **How to work this handoff (learning mode).** Luis is using this part to learn the transactional
> outbox, background work in FastAPI and the claiming pattern. Claude Code shows **one code change at
> a time** (a column, a function, a query, a config field), explains what it does and why it's
> written that way, and then **waits**. Luis decides per change: he writes it himself and Claude Code
> reviews it, or Claude Code writes it. Never batch changes, never "I'll do the rest". When Luis
> writes a change, review it like a PR comment: what's right, what's wrong, why. Commits stay one per
> stage, when Luis says the stage is done.

**Decided (don't re-open):**

- **Comments never depend on email.** With `CONVERSATION_EMAILS_ENABLED=false` (the default)
  nothing in this handoff runs: no rows, no tasks, no sweeper, no calls. With it on, a failure to
  plan or send an email must never fail or slow down the comment request.
- **Transactional outbox:** `conversation_notifications` rows are inserted in the **same
  transaction** as the comment, so a comment can't exist without its notifications or the reverse.
- **Payload snapshot:** each row stores the exact payload sent to auth-server (JSONB), built when
  the row is inserted. Retries send it unchanged, which the Resend idempotency key requires (same
  key + different payload = rejected).
- **Fast path:** the comment route adds one `BackgroundTasks` task with the new row ids. The task
  runs after the response, with its **own** DB session (the request's is closed by then).
- **Sweeper:** an asyncio loop started in `lifespan`, on every API task, every 2 minutes with a
  random 0–30 s start offset. DB work runs in `anyio.to_thread.run_sync` (the DB layer is sync).
- **Claiming = lease:** a claim sets `status='sending'`, `next_attempt_at=now()+2 min`. The sweeper
  claims with `FOR UPDATE SKIP LOCKED`; the fast path claims by id with the same conditions. Any
  number of API tasks can run both safely.
- **Retry schedule:** failed → retry after 1, 5, 15, 60 minutes; the 5th failure → `dead` (logged).
  New rows start at `next_attempt_at = now() + 60 s` so the fast path has a head start.

Branch **`report-conversations-email`**. Each stage: `uv run ruff check .`, `uv run ty check`,
`alembic check` when the schema changes.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Config, tables, migration | ⬜ | |
| 2. Recipients and planning rows in the comment transaction | ⬜ | |
| 3. auth-server client | ⬜ | |
| 4. Claim and send; fast path with `BackgroundTasks` | ⬜ | |
| 5. Sweeper loop | ⬜ | |
| 6. Opt-out endpoints | ⬜ | |
| 7. Docs and a local end-to-end run | ⬜ | |

### Decisions and deviations

- (fill in per stage)

## Stage 1: Config, tables, migration

**Config** (`api/config.py`): `conversation_emails_enabled: bool = False`; reuse
`internal_api_token` (already there for the incoming calls) as the outgoing token; the auth-server
base URL for server-to-server calls is the same internal base the JWKS fetch uses (read the
existing `auth_server_url` / internal-URL comments and reuse, don't add a third URL). Validation: on
with no token → startup error outside local.

**`conversation_notifications`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | identity PK | Also the idempotency key's suffix |
| `conversation_id` | FK `report_conversations.id` ON DELETE CASCADE | |
| `comment_id` | FK `report_conversation_comments.id` ON DELETE CASCADE | The comment that caused it |
| `recipient_user_id` | `VARCHAR NOT NULL` | auth-server user id |
| `kind` | `VARCHAR(8)` | `new` \| `reply` (CHECK) |
| `payload` | `JSONB NOT NULL` | Exactly what is POSTed to auth-server |
| `status` | `VARCHAR(8) NOT NULL` | `pending` \| `sending` \| `sent` \| `failed` \| `dead` (CHECK) |
| `attempts` | `SMALLINT NOT NULL DEFAULT 0` | |
| `next_attempt_at` | `timestamptz NOT NULL` | |
| `last_error` | `TEXT NULL` | Short: status code or exception class, no PII |
| `created_at` / `sent_at` | `timestamptz` | |

Indexes: **partial** `ix_conversation_notifications_due` on `(next_attempt_at)` `WHERE status IN
('pending','failed','sending')` (the sweeper's only index; sent and dead rows drop out of it), and
`(recipient_user_id, conversation_id, created_at)` for the throttle.

**`notification_preferences`**: `user_id VARCHAR PK`, `conversation_emails BOOLEAN NOT NULL DEFAULT
true`, `updated_at`. A missing row means the defaults.

## Stage 2: Recipients and planning rows

**Files:** `data/small_groups/conversation_notifications.py` (new: planning and recipients),
`conversation_services.add_comment`.

`plan_notifications(session, conversation, comment) -> list[int]` runs inside `add_comment` after the
comment is flushed and before the commit, only when the setting is on. Returns the new row ids.

Recipients (spec, Part 2):

- **A thread started by an elders'-side comment** (the comment created the thread): the group's
  **current** leaders and co-leaders (active period, `left_at IS NULL`) with a linked user
  (`members.user_id` not null). `kind='new'`, `reason='leader'`.
- **A thread started by a leaders'-side comment:** nobody.
- **A reply:** every other author of a non-deleted comment in the thread (`reason='participant'`),
  plus, when the reply is on the elders' side, the group's current leaders and co-leaders
  (`reason='leader'`). `kind='reply'`. De-duplicate by user id (participant wins).
- Never the author. Skip users whose `notification_preferences.conversation_emails` is false.
- **Throttle:** skip a recipient who already has a row for this conversation with `created_at` after
  their `report_conversation_reads.last_read_at` (or any row, if they never read it). "One email per
  thread until you open it."

Payload: `notificationId` is only known after insert: insert with the payload minus the id, flush,
then set `payload['notificationId'] = row.id` (or build the key from the row id at send time and
leave it out of the payload; pick one and note it). `path` =
`/groups/reports/{report_id}?person={member_id}`; `actorName` = the author member's name;
`groupName`, `meetingDate` from the report.

Wrap planning in a savepoint: if planning raises, log it, roll back the savepoint, and let the
comment commit without notifications. A bug here must not lose the comment.

Check by hand: each recipient rule, the throttle (comment twice before the leader opens: one row),
opt-out, a leader with no linked user (no row), an elder replying to a leader-started thread
(leaders get `reply` rows).

## Stage 3: auth-server client

**File:** `api/auth_server_client.py` (or `data/notifications/sender.py`; note where).

- Add `httpx` as a dependency (`uv add httpx`); one module-level `httpx.Client` with a 5 s timeout,
  base URL from Stage 1, header `X-Internal-Token`.
- `send_notification(payload) -> SendOutcome` where the outcome is `sent` / `retry` / `dead`, mapped
  from auth-server's codes: 200 → sent; 422, 410, 409 → dead (409 also logged as an error: it means
  the payload changed under the same key); 401 → dead and an error log (misconfigured token);
  503, other 5xx, timeouts, connection errors → retry.
- Never log the payload (names) or the token.

## Stage 4: Claim and send; fast path

**Files:** `conversation_notifications.py` (claim, send, outcome), the comment route.

- `claim(session, ids=None, limit=50) -> list[Row]` in one transaction:
  `SELECT … WHERE status IN ('pending','failed','sending') AND next_attempt_at <= now()`
  `[AND id = ANY(:ids)] ORDER BY next_attempt_at LIMIT :limit FOR UPDATE SKIP LOCKED`, then
  `UPDATE … SET status='sending', next_attempt_at=now()+interval '2 minutes'`, commit, return.
  **For the fast path, the `next_attempt_at <= now()` condition is dropped** (it claims its own
  fresh rows by id), but `status IN ('pending')` stays, so it never takes a row the sweeper holds.
- `deliver(row_id, payload)`: calls the client **outside any transaction**, then records the
  outcome in a new short transaction: `sent` (`sent_at`), `failed` (`attempts+1`, backoff,
  `last_error`) or `dead`. Retry delays: `[1, 5, 15, 60]` minutes by `attempts`; reaching 5 → `dead`.
- `process(ids=None)`: claim, then deliver each. Both entry points call this one function.
- Fast path: `add_comment` returns the planned ids; the route takes `background_tasks:
  BackgroundTasks` and adds `process_in_new_session(ids)` when there are any. Plain `def` task:
  Starlette runs it in the thread pool after the response. Exceptions are caught and logged inside
  the task (an exception there is otherwise silent).

Check: the response returns before the send (add a temporary sleep in the client to see it); kill
auth-server and comment: the row ends `failed` with `attempts=1` and the comment is fine.

## Stage 5: Sweeper loop

**Files:** `api/main.py` (`lifespan`), `conversation_notifications.py` (`sweep_once`).

```python
async def _sweep_forever() -> None:
    await asyncio.sleep(random.uniform(0, 30))
    while True:
        try:
            await anyio.to_thread.run_sync(sweep_once)  # its own session; process(ids=None)
        except Exception:
            logger.exception("conversation notification sweep failed")
        await asyncio.sleep(120)
```

- Started in `lifespan` only when the setting is on (`task = asyncio.create_task(...)`); on shutdown
  `task.cancel()` and await it (suppress `CancelledError`) **before** disposing the engines.
- `sweep_once` loops `process()` while a batch comes back full (50), so a backlog drains in one run,
  with a cap (e.g. 10 batches) so one run can't hog the thread pool.
- Log at INFO only when it did something ("sent 3, failed 1, dead 0"), DEBUG otherwise.

Check: stop auth-server, comment, start auth-server: the sweeper sends it within ~3 minutes of its
`next_attempt_at`. Run two API processes against one DB: each row is sent once. A row stuck in
`sending` (kill the process mid-send) is picked up after its lease.

## Stage 6: Opt-out endpoints

- `GET /me/notification-preferences` → `{ "conversationEmails": true, "emailsEnabled": false }`
  (`emailsEnabled` = the server setting, so the staff app can hide the toggle while emails are off).
- `PUT /me/notification-preferences` body `{ "conversationEmails": bool }`, upsert by `sub`. Any
  signed-in user. Rate limit 20/minute.

## Stage 7: Docs and a local end-to-end run

- `docs/ARCHITECTURE.md`: the outbox, the two entry points, the lease, the retry table, the setting.
  One line in `CLAUDE.md`.
- End-to-end locally with the setting on, auth-server running with a Resend test key: elder comments
  → leader's email; leader replies → elder's email; second elder comment before the leader opens →
  no second email.
- Mark this log done; update the cross-repo spec only where the build differs.

## Not in this spec

- Push notifications (they'd be another consumer of the same outbox rows: a `channel` column later).
- Digests, an admin view of dead rows (query the table for now), purging old `sent` rows.
