# Report conversations, Part 2: email notifications (membership-management)

Handoff spec for the API side of **conversation emails**, rewritten Nov 2026 around the event-first
design: the comment transaction writes one `outbox_events` row; a **worker** (its own entry point,
embedded in the API by default) turns each event into notification requests through the
**report-conversations consumer** (audience, recipients, watchers, unwatch, throttle), hands them
to a **generic `notifications/` layer** (preferences, deliveries, `Sender`), and sends them
through auth-server.

- Cross-repo rules: `../docs/specs/report-conversations.md`: rules 18–23 (*Watching groups*),
  *Contracts (Part 2: email)* and *Changes to the Part 2 handoffs (Nov 2026)*. Section threads:
  `../docs/specs/prayer-follow-up.md`, *Changes for report conversations Part 2* (applied here:
  `?section=` paths and `topic`).
- auth-server's side: `../auth-server/docs/REPORT-CONVERSATIONS-EMAIL-HANDOFF.md` (merged, PR #35;
  its *Decisions and deviations* are the contract as built, summarised below).
- staff-app's side: `../staff-app/docs/design/REPORT-CONVERSATIONS-EMAIL.md` (uses Stage 6's
  routes).
- Part 1: `docs/REPORT-CONVERSATIONS-API-HANDOFF.md`, plus Parts 1b–1d (`UNREAD-TAB`, `UNREAD-DOT`,
  `RESOLVED-PERIOD` handoffs).

> **How to work this handoff (learning mode).** Luis is using this part to learn the transactional
> outbox, background work in FastAPI and the claiming pattern. Claude Code shows **one code change at
> a time** (a column, a function, a query, a config field), with the code and a short why, then
> **waits**. Luis decides per change: he writes it himself and Claude Code reviews it like a PR
> comment (what's right, what's wrong, why), or he says "you write it". Never batch changes, never
> "I'll do the rest". Commits stay one per stage, made only when Luis says the stage is done, with
> this progress log updated in the same commit. Stop after every stage and before any PR. Docs
> changes (this file, `ARCHITECTURE.md`, `CLAUDE.md`) don't need the step-by-step review.

**Depends on:** auth-server Stage 3 (`POST /internal/notifications`) and Stage 4 (the two user
routes), both on its `main`. Nothing here may stub them.

Branch **`feature/report-conversations-email`** (the spec's older `report-conversations-email`
predates the branch naming rule). Each stage: `uv run ruff check .`, `uv run ty check`, and
`uv run alembic check` plus a `downgrade -1` / `upgrade head` round trip when the schema changes.

**Testing with real email:** auth-server's local `.env` has a real send-only Resend key, so a send
reaches a real inbox. Only send to Luis's test accounts (ask him for the next unused sign-in). Never
put an email address in a command, a log line or this file: use user ids.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 0. Handoff rewritten to the Nov 2026 design | ✅ | `79ba508` |
| 1. Config, the five tables, migration | ✅ | `c9ff673` |
| 2. Shared read check; the event in the comment transaction; the consumer; `notifications/` | ✅ | (this commit) |
| 3. auth-server client: `with-permission`, `permissions`, the `Sender` | ⬜ | |
| 4. Claiming, the fence, processing, sending, outcomes; the fast path | ⬜ | |
| 5. The worker: entry point, embedded start, SIGTERM, gate, expiry, monitoring, purge | ⬜ | |
| 6. Preference and watch routes; docs; the end-to-end hand-check | ⬜ | |

### Decisions and deviations

- Stage 0: the old handoff (per-recipient `conversation_notifications` rows planned inside the
  comment transaction, a sweeper in `lifespan`, `attempts`-only retries, 5th failure → `dead`) is
  replaced by the spec's Nov 2026 design. Nothing from it was built.
- Stage 0: **possible watchers** are fetched with all four permissions the full-scope audience needs
  (`smallGroups:all`, `smallGroups:view`, `smallGroupReports:view`,
  `smallGroupReports:viewObservations`), not only `smallGroups:all`. Still a superset: the shared
  check (rule 23) decides who watches each group, so the rule keeps one copy.
- Stage 0: **status codes beyond the spec's table**, from auth-server as built: 422
  `invalid_request` → `dead` with an error logged (a bug, like `invalid_data`); 503
  `internal_api_disabled` (token unset there) and 500 `internal_error` → transient, error logged;
  404 `recipient_unavailable` also covers **unverified** users → `dead`.
- Stage 0: users returned by `POST /internal/users/permissions` with `{}` (`pending` role) and users
  absent from the response both count as "can't read".
- Stage 0: requests are sent as ASCII-escaped JSON (`content=json.dumps(body, ensure_ascii=True)`
  plus `Content-Type: application/json`), not httpx's `json=` (httpx 0.28 sends raw UTF-8).
  auth-server's Stage 3 notes it expects that; names with accents stay safe either way, but the
  escape removes the question.
- Stage 0: `CONVERSATION_EMAILS_ENABLED=true` without `INTERNAL_API_TOKEN` is a startup error **in
  every environment**, local included: auth-server answers 503 `internal_api_disabled` without the
  token, so every event would retry for 24 h and expire.
- Stage 1 files: `notifications/config.py` (`NotificationSettings`, `notification_settings`;
  `auth_server_url` trailing slash stripped like `ApiSettings`'), `embedded_worker` in
  `api/config.py`, `data/claim_columns.py` (`ClaimColumns` mixin), `data/outbox/models/`
  (`OutboxEvent`), `data/notifications/models/` (`NotificationDelivery`, `NotificationPreference`),
  `data/small_groups/models/` (`ReportConversationNotifyState`, `SmallGroupWatchOptOut`); the two
  new packages registered in `data/models.py`. `.env.example` gains both variables, and its
  `INTERNAL_API_TOKEN` note says the token is also sent to auth-server.
- Stage 1: the claim columns are a **mixin**, so both tables get the same columns with one
  definition; each table keeps its own `status` CHECK (the sets differ) and its partial due-index,
  which includes the in-progress status so an expired lease is found by the same scan.
  `status`/`attempts`/`failures` have **server defaults** (Stage 4's raw SQL relies on the DB's
  starting values); `next_attempt_at` and `expires_at` have none, so every insert chooses them.
- Stage 1: `outbox_events` and `notification_deliveries` use `BIGINT` identity ids (the other tables
  use `INTEGER`): one event per comment and the ids end up in idempotency keys. Events'
  `created_at` has **no default** (the writer sets it to the comment's `created_at`); deliveries'
  defaults to `now()` (their deadline is the inherited `expires_at`).
- Stage 1: `category`/`channel` have no CHECK: the generic layer takes a new category or a `push`
  channel without a migration. Preferences are one row per `(user, category, channel)`, written on
  every `PUT` (also when re-enabling), not deleted.
- Stage 1: `small_group_watch_opt_outs` has only its PK `(user_id, small_group_id)`: the consumer's
  "who of these opted out of group G" reads tens of rows, so no second index.
- Stage 1: migration `b453135219c0` (autogenerated, not edited): five tables, two partial indexes.
  Checks: `alembic check` clean, `downgrade -1` + `upgrade head` round trip, both partial indexes
  present with their `WHERE`, a bogus `status` rejected by each CHECK.
- Stage 1: `uv run ruff check .` reports 3 errors in `.claude/hooks/check.py`, unchanged from
  `main` (commit `a1daac1`); `ruff check src` and `ty check` are clean. Left alone here (not this
  feature); worth a `chore/` fix.
- Stage 2: **the shared rule lives in `data/small_groups/access_rules.py`, not `api/access.py`**
  (deviation from the spec's wording): `api/access.py` imports FastAPI and `api_settings`, and the
  worker must import nothing from the API. `SmallGroupScope` moved there too (re-imported by
  `access.py`, so the routers' imports didn't change), with `Perms`, `holds`,
  `small_group_scope_for` and `can_read_group_conversations`. Still one copy: `_small_group_scope`,
  `conversation_access` and `conversation_group_ids` call it. `Perms` is a plain alias, not a `type`
  statement (`ruff.toml` targets py310).
- Stage 2: `_small_group_scope` only queries the led groups when the rule can use them (a member,
  `smallGroups: view`, not `all`), so full-scope requests cost what they did. `conversation_group_ids`
  asks the rule once with a placeholder id `0` for a full scope (the rule ignores the id there).
- Stage 2 check (2a): the old and new helpers compared in a scratch script over every combination of
  the four permissions × member or not × in or out of scope (64 cases): same scope, same list filter,
  same 404/403/allowed. The live role pass is in Stage 6's end-to-end run (decided with Luis).
- Stage 2: **"starts the thread" is decided under the thread lock** by "no comment yet, deleted ones
  included", not by "this request created the row": two first comments at once → one `new`, one
  `reply`; a thread whose first comment was deleted stays a reply. `startedBy` is the side of the
  thread's first comment, deleted or not (`first_comment_side_query`).
- Stage 2: the event is added in `add_comment` only while the switch is on (with a `flush` for the
  comment id); `add_comment`'s return value is unchanged until Stage 4 needs the event id.
- Stage 2: **leaders of a closed group get `leader` emails** (decided with Luis, beyond the spec's
  "current leaders"): `group_leader_user_ids_query` uses `leads_in_scope_condition`, the periods the
  scope uses, so for a closed group it's the leaders when it closed, who can still open its threads
  (rule 13). For an open group it's the active leaders, as before.
- Stage 2: the candidate snapshot (`candidate_user_ids`) is only a set of user ids: the
  leader/participant/watcher split is redone inside the transaction from fresh rows and kept to the
  users present in `perms_by_user`, so "nobody is added inside the transaction" needs no second
  list. Watchers join the snapshot only for leaders'-side comments; the author never does.
- Stage 2: the read check for many users (`readers_of_group`) is two queries per event (linked
  members, then their led groups with `led_small_group_ids_by_member_query`, the batch form of the
  scope query) and the shared rule in memory. Full-scope users need no linked member to watch (they
  read through `viewObservations`, as in the app); locally two of the three are unlinked and got
  watcher deliveries.
- Stage 2: the recipient rules are a pure function (`choose_recipients`); the consumer's entry point
  is `process_comment_added`, which calls `notifications.deliveries.create_deliveries` itself (domain
  → notifications, one way). `notifications/deliveries.py` holds `NotificationRequest`,
  `create_deliveries` (one preferences query per event, `ON CONFLICT DO NOTHING` on the unique key,
  `next_attempt_at = now()`, `expires_at` = the request's `not_after`) and `is_enabled`.
- Stage 2: `actorName` is trimmed and cut to 200 like `groupName`; auth-server didn't state a limit
  for it, so the cut is ours, to be safe.
- Stage 2: `dict(session.execute(...))` doesn't work (a `Result` has `.keys()`, so `dict()` reads it
  as a mapping); comprehensions instead.
- Stage 2 checks (local, every write in a rolled-back transaction): the event's payload, head start
  and deadline; `startsThread` true then false; the throttle's eight cases (first email, held until
  opened, already read, read exactly at the comment, out of order doesn't move the stamp back);
  readers of an open and a closed group against real `perms` from auth-server; then
  `process_comment_added` on real comments: elder starts → the leader (`new`, `leader`); leader
  replies → the elder (`participant`) and the watchers; again before opening → nothing; after
  opening → the elder; leader starts → every watcher; after unwatching → not that elder; perms
  missing → nothing; the leader's emails off → nothing; comment deleted first → no candidates, no
  deliveries; `?section=` / `?guest=` / `?person=` paths and topics. Two events in one thread *at
  the same moment* need two concurrent transactions: checked in Stage 4 with the worker.
- Stage 2: two queries were appended to `conversation_queries.py` with a shell heredoc instead of
  Edit (the workspace rule); content as reviewed, and Edit/Write only since.
- (fill in per stage)

## Contract as built (auth-server, PR #35)

Every `/internal/*` call sends `X-Internal-Token` = this repo's existing `INTERNAL_API_TOKEN`, to
`AUTH_SERVER_URL` (the internal origin the JWKS fetch already uses; no new URL). Error bodies are
`{ code, message }`. Common: 401 `invalid_token`, 503 `internal_api_disabled`, 500
`internal_error`; a **bare 404** (no `code`) = route not deployed.

- **`POST /internal/notifications`**, strict body `{ idempotencyKey (≤ 200), recipientUserId,
  template, data, path }`; any extra key → 422.
  - `template`: `report-conversation.new` | `report-conversation.reply`.
  - `data`: `{ actorName, groupName (trimmed, 1–200), meetingDate "YYYY-MM-DD", reason
    leader|participant|watcher, topic person|prayer|praise|followUp, startedBy elders|leaders }`.
  - `path` must match `/groups/reports/{id}?person={id}` | `?guest={id}` |
    `?section=prayer|praise|followUp`.
  - 200 `{ sent, emailId }` (a repeat too). 404 `recipient_unavailable` (missing, unverified or
    banned). 409 `idempotency_conflict`. 422 `invalid_request` / `unknown_template` /
    `invalid_data` (bodies over 16 KB too). 503 `send_failed`: retry with the same key.
  - The request hash is taken after trimming, so whitespace-only differences don't 409. Language
    comes from `user.locale`, default `en`.
- **`GET /internal/users/with-permission?permission=a:b&permission=c:d`** → `{ userIds }`: users
  holding all of them, sorted, banned left out. 1–20 values, each must exist in `statements.ts`,
  else 422 `invalid_permission`. No paging.
- **`POST /internal/users/permissions`** `{ userIds: 1–500 }` → `{ users: { id: perms } }`, the
  JWT's `perms` shape. Unknown and banned users are absent; `pending` users get `{}`. More than 500
  ids, or over 64 KB → 422 `invalid_request`.

### Sender outcome table (both sides agree)

| auth-server answers | Delivery becomes |
| --- | --- |
| 2xx | `sent` (`sent_at`) |
| 410, or 404 `recipient_unavailable` | `dead` |
| 409 `idempotency_conflict` | `dead`, error logged (same key, other payload: a bug) |
| 422 `invalid_request` / `unknown_template` / `invalid_data` | `dead`, error logged |
| bare 404 | transient, error logged (deploy order, wrong base URL) |
| 401, 403 | transient, error logged (token rotation, bad config) |
| 408, 429, 5xx (`send_failed`, `internal_api_disabled`, `internal_error`), timeout, connection error | transient |

## Decided (don't re-open)

- **Comments never depend on email.** With `CONVERSATION_EMAILS_ENABLED=false` (the default):
  no event rows, no worker, no fast path, no calls to auth-server. With it on, nothing in the
  comment request waits on or fails because of email: the transaction only adds one row.
- **Event first.** The comment transaction inserts the comment and one `outbox_events` row
  (`report_conversation.comment_added`, `next_attempt_at = now() + 60 s`). Nothing else.
- **One way across the boundary.** The consumer (domain) decides who should hear and why, and
  hands every survivor (audience, unwatch, throttle) to `notifications/`, which drops those whose
  preference for the category and channel is off as it inserts deliveries. The consumer never
  reads preferences; `notifications/` never imports conversation code.
- **One copy of the read rule** (rule 23): `small_group_scope_for` and
  `can_read_group_conversations` in `api/access.py`, pure functions used by the API and the worker.
- **Pinned candidate snapshot, no network call inside a transaction.** Permissions are fetched for a
  batch's candidates before any event is processed; each event uses exactly that set.
- **Claiming is a lease** with a claim token, `attempts` counted at claim (the poison counter),
  `failures` driving the backoff, every later write fenced by the token, and for events the fence
  is the first statement of the processing transaction.
- **Numbers:** batch 10, lease 2 min, sender timeout 5 s (`lease > batch × timeout + margin`),
  backoff 1, 5, 15, 60 min then hourly, poison cap 5, one 24 h deadline per comment (deliveries
  inherit the event's `expires_at`), purge after 30 days (events) / 90 days (deliveries).
- **The worker imports nothing from FastAPI.** `python -m membership_management.worker`; embedded in
  the API by default (`EMBEDDED_WORKER=true`) through its own `anyio.CapacityLimiter(1)`.
- **Privacy:** no comment text, section text or member/guest name of the row's person in any event,
  delivery or log. `actorName` (the comment author) and `groupName` are the only names, and they go
  only to auth-server.

## Where things go

| What | Where |
| --- | --- |
| Settings the worker needs (enabled, auth URL, token) | `notifications/config.py` (new, outside `api/`, so the worker doesn't import `ApiSettings`); `EMBEDDED_WORKER` in `ApiSettings` |
| `OutboxEvent` model | `data/outbox/models/` (generic) |
| `NotificationDelivery`, `NotificationPreference` models | `data/notifications/models/` (generic) |
| `ReportConversationNotifyState`, `SmallGroupWatchOptOut` models | `data/small_groups/models/` (domain) |
| Claim / fence / release / outcome helpers shared by both tables | `data/claiming.py` |
| Report-conversations consumer | `data/small_groups/conversation_notifications.py` |
| Preferences, delivery insert, sending, `Sender` protocol | `notifications/` (generic package) |
| auth-server client | `notifications/auth_server.py` (the `Sender` and the two user lookups) |
| Worker | `worker/__main__.py`, `worker/runner.py` (`run_once`, `run_forever`) |

Every new model package is imported in `data/models.py`. Exact file names can move; note it here.

## Stage 1: Config, the five tables, migration

**Config.**

- `notifications/config.py`: `NotificationSettings(BaseSettings)`, same `.env` handling as the
  other settings (`env_file.py`): `conversation_emails_enabled: bool = False`
  (`CONVERSATION_EMAILS_ENABLED`), `auth_server_url` (same `AUTH_SERVER_URL` the API reads),
  `internal_api_token: SecretStr | None` (same `INTERNAL_API_TOKEN`). Validator: enabled without a
  token → error, every environment (see *Decisions*).
- `api/config.py`: `embedded_worker: bool = True` (`EMBEDDED_WORKER`).
- `.env.example`: both variables with a one-line comment each.

**Tables** (one migration; review the autogenerated file, then the round trip).

`outbox_events` (generic, **no foreign keys**):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | identity PK | |
| `event_type` | `VARCHAR(64) NOT NULL` | `report_conversation.comment_added` |
| `schema_version` | `SMALLINT NOT NULL` | 1 |
| `aggregate_type` / `aggregate_id` | `VARCHAR(64)` / `BIGINT`, NOT NULL | `report_conversation`, the conversation id |
| `payload` | `JSONB NOT NULL` | ids and facts only |
| claim columns | see below | statuses `pending \| processing \| processed \| failed \| dead \| expired` |
| `created_at` / `processed_at` | `timestamptz` | `processed_at` null until processed |

`notification_deliveries` (generic):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | identity PK | the idempotency key is `mm:notification-delivery:{id}` |
| `source_event_id` | `BIGINT NOT NULL` | **no FK** (events purged after 30 days, deliveries after 90) |
| `recipient_user_id` | `VARCHAR NOT NULL` | auth-server user id |
| `category` / `channel` | `VARCHAR(32)` NOT NULL | `report_conversation` / `email` |
| `template` | `VARCHAR(64) NOT NULL` | |
| `payload` | `JSONB NOT NULL` | exactly what the `Sender` sends; never changed after insert |
| claim columns | see below | statuses `pending \| sending \| sent \| failed \| dead \| expired \| suppressed` |
| `created_at` / `sent_at` | `timestamptz` | |

Unique `(source_event_id, recipient_user_id, channel)`.

**Claim columns** (both tables): `status` (CHECK), `attempts SMALLINT NOT NULL DEFAULT 0`,
`failures SMALLINT NOT NULL DEFAULT 0`, `next_attempt_at timestamptz NOT NULL`, `claim_token uuid
NULL`, `expires_at timestamptz NOT NULL`, `last_error VARCHAR(200) NULL` (status code, error `code`
or exception class; no PII). Partial index on `(next_attempt_at)` where status is pending, failed or
in progress, one per table.

`notification_preferences` (generic): PK `(user_id, category, channel)`, `enabled BOOLEAN NOT
NULL`, `updated_at`. No row = enabled.

`report_conversation_notify_state` (domain): PK `(user_id, conversation_id)`, `conversation_id`
FK → `report_conversations` ON DELETE CASCADE, `last_notified_at timestamptz NOT NULL`.

`small_group_watch_opt_outs` (domain): PK `(user_id, small_group_id)`, `small_group_id` FK →
`small_groups` ON DELETE CASCADE, `created_at`. No row = watching.

Check: `alembic check` clean, round trip, CHECKs reject a bad status, the partial indexes exist.

## Stage 2: Shared read check, the event, the consumer, `notifications/`

**2a. The shared read check** (`api/access.py`), behaviour unchanged:

- `small_group_scope_for(perms, led_group_ids, member_id) -> SmallGroupScope | None`: today's
  `_small_group_scope` without the claims and the DB (`None` without `smallGroups: view`; full with
  `smallGroups: all`; otherwise the groups the member leads, or led when the group closed).
- `can_read_group_conversations(perms, scope, small_group_id) -> bool`: `smallGroupReports: view`;
  a full scope needs `viewObservations`; a scoped user needs the group in their scope.
- `get_small_group_scope`, `conversation_access` and `conversation_group_ids` call them. The DB
  part that finds the led groups becomes a helper the worker can call for many users at once.
- Check: every Part 1 conversation route by role (admin, elder, leader, co-leader of a closed
  group, deacon, user) answers as before.

**2b. The event in the comment transaction** (`conversation_services.add_comment`, only when
enabled): one `OutboxEvent` with payload v1 `{ conversationId, commentId, side, authorUserId,
startsThread, occurredAt }`, `occurredAt` = the comment's `created_at` exactly (ISO 8601 with
offset), `expires_at = created_at + 24 h`, `next_attempt_at = now() + 60 s`. Returns the event id
for the fast path (Stage 4).

**2c. The consumer** (`data/small_groups/conversation_notifications.py`), in two halves so the
network call sits between them:

- `candidates_for(session, event) -> set[str]` (read-only): the group's current leaders and
  co-leaders with a linked user, the thread's non-deleted comment authors, and (passed in) the
  possible watchers. Empty when the comment or conversation is gone or soft-deleted.
- `plan(session, event, perms_by_user, now) -> list[NotificationRequest]`, inside the event's
  transaction:
  - Comment or conversation gone, or comment `deleted_at` set → no requests (the event still ends
    `processed`).
  - Recipients: elders'-side start → leaders (`leader`); leaders'-side start → watchers
    (`watcher`); reply → other non-deleted authors (`participant`), plus leaders for an elders'-side
    reply, plus watchers for a leaders'-side reply.
  - Each candidate must pass `can_read_group_conversations` with their snapshot `perms` and a scope
    built from `members.user_id` the way the API does; missing or `{}` = can't read. Watchers too.
  - Watchers who opted out of the group are dropped **as watchers only**.
  - De-duplicate (`participant` > `leader` > `watcher`); never the author.
  - The throttle statement from the spec, one statement for all recipients sorted by `user_id`,
    stamped with `occurredAt`; only the users it returns go on.
  - `data`: `actorName` (author member's name), `groupName` (trimmed, cut to 200), `meetingDate`
    (`YYYY-MM-DD`), `reason`, `topic` (`person` for a member or guest row, else the section key),
    `startedBy` (side of the thread's first comment, deleted or not). `template` is `.new` when
    `startsThread`, else `.reply`. `path` by anchor: `?person=`, `?guest=` or `?section=`.
  - Each request carries the event's `expires_at` as its "not after".

**2d. `notifications/`**: `create_deliveries(session, source_event_id, requests)`: drop users whose
preference for `(category, channel)` is off (one query), insert the rest `ON CONFLICT DO NOTHING`
with `next_attempt_at = now()`, `expires_at` = the request's "not after". `is_enabled(session,
user_id, category, channel)` for the re-check before sending.

Hand-checks (direct calls with fixed `perms`, no auth-server yet; the full run is in Stage 6): each
recipient rule; an elder who unwatched gets nothing unless they commented; a leader who stepped down
or whose `perms` lack `smallGroupReports: view` is dropped; a deleted comment → no requests; a read
after the comment → no request; two events in one thread → one request per user.

## Stage 3: auth-server client

`notifications/auth_server.py`:

- `httpx` as a direct dependency of the root package (`uv add httpx`; today it's only in the lock
  through another package). One module-level `httpx.Client`: base URL `AUTH_SERVER_URL`, header
  `X-Internal-Token`, 5 s timeout. Bodies as ASCII-escaped JSON (*Decisions*).
- `users_with_permissions(perms: list[str]) -> list[str]`: the possible watchers.
- `permissions_for(user_ids) -> dict[str, Perms]`: chunks of at most 500, merged; any failed chunk
  raises a transient error for the whole lookup (no partial data).
- `AuthServerSender.send(payload, idempotency_key) -> SendOutcome` (`sent` | `dead` |
  `transient`, plus a short `last_error`), mapping the outcome table above. The `Sender` protocol
  lives in `notifications/`; this is its only implementation.
- Errors logged with the status code and the error `code`, never the token, the payload or an
  address.

Check (auth-server running): each call against the real routes; wrong token → 401 → transient;
an unknown route path (temporary) → bare 404 → transient; `with-permission` returns the admins and
the elder.

## Stage 4: Claiming, the fence, processing, sending, outcomes; the fast path

`data/claiming.py` (both tables) and the processing/sending code in `worker/` and `notifications/`:

- **Claim:** `SELECT … WHERE status IN (pending, failed, in progress) AND next_attempt_at <= now()
  ORDER BY next_attempt_at LIMIT 10 FOR UPDATE SKIP LOCKED`, and in the same statement (CTE +
  `UPDATE … RETURNING`) set the in-progress status, a new `claim_token`, `attempts + 1`,
  `next_attempt_at = now() + 2 min`. Rows past `expires_at` → `expired`; rows claimed with
  `attempts` already at 5 → `dead`. The fast path claims its one id with the same statement plus
  `id = :id`, without `next_attempt_at <= now()` (its row is 60 s in the future) and only while
  `pending`, so it never takes a row the sweep holds.
- **Process events:** look up the batch's candidates (read-only), then their permissions (Stage 3;
  failure = transient for every claimed event). Then per event, one transaction whose **first
  statement is the fence** (`UPDATE outbox_events SET status='processed', processed_at=now() WHERE
  id=:id AND claim_token=:token RETURNING id`; no row = lease lost, roll back, stop), then the
  consumer, then `create_deliveries`, then commit. An exception rolls everything back and a
  **second short fenced transaction** records `failed`, `failures + 1`, `last_error`, backoff.
- **Send deliveries:** per claimed row: expired → `expired`; preference off now → `suppressed`
  (final, throttle row left); else `Sender.send` and record the outcome, fenced.
- **Three outcome kinds:** transient → give the attempt back (`attempts - 1`), `failures + 1`,
  `failed`, backoff by `failures`, and while sending **stop the batch**, releasing the untried rows
  (fenced, `pending`, `attempts - 1`, `next_attempt_at` unchanged); exception → `failures + 1`,
  attempt kept, backoff; permanent → `dead`.
- **Fenced writes:** zero rows updated = someone else owns the row: log and undo nothing.
- **Fast path:** the comment route takes `BackgroundTasks` and, when an event was written, adds a
  plain `def` task with its own session: fetch possible watchers, claim the one event, fetch its
  candidates' permissions, process it, send its deliveries. All exceptions caught and logged inside.

Hand-checks: the response returns before the send; kill the process mid-batch → no duplicate email,
`attempts` went up, the lease releases it; a processing exception (temporary `raise`) → `failed`
with `last_error`; Resend/auth-server 503 → retries, nothing `dead`; a wrong token or a bare 404 →
retries with an error logged; "Conversation emails" turned off before the send → `suppressed`.

## Stage 5: The worker

- `worker/runner.py`: `run_once()` = expire due rows, then (if the gate passes) process due events,
  send due deliveries, then purge; `run_forever(stop_event)` every 2 minutes after a random 0–30 s
  start offset, catching and logging each run's exception.
- **Reachability gate:** each sweep fetches the possible-watcher list before claiming; if that
  fails, it claims nothing from either table this sweep (expiry and purge still run).
- `worker/__main__.py`: `python -m membership_management.worker`; SIGTERM/SIGINT set the stop event:
  stop claiming, finish or abandon the item in hand (leases cover it). Exits at once when emails are
  disabled.
- **Embedded:** with emails enabled and `EMBEDDED_WORKER=true`, `lifespan` starts `run_forever` as
  a task, running its sync work with `anyio.to_thread.run_sync(…, limiter=CapacityLimiter(1))`;
  on shutdown it sets the stop event and awaits the task **before** disposing the engines.
- **Monitoring:** each run logs the age of the oldest pending row and the `dead` count per table
  (INFO when it did something or something is dead, DEBUG otherwise).
- **Purge:** `processed`/`expired`/`dead` events older than 30 days, `sent`/`dead`/`expired`/
  `suppressed` deliveries older than 90 days, in bounded batches.

Hand-checks: auth-server stopped for a while (two hours for the real check, Stage 6) → nothing
claimed, nothing `dead`, everything sends once it's back; an event older than 24 h → `expired`; an
event processed 23 h after its comment whose send keeps failing → the delivery expires at the
comment's 24 h mark; `python -m membership_management.worker` + Ctrl+C exits cleanly; two
processes against one DB → each email once.

## Stage 6: Preference and watch routes; docs; the end-to-end hand-check

**Routes** (`CamelModel`, default rate limit; the two `PUT`s also 20/minute):

| Route | Permission | Shape |
| --- | --- | --- |
| `GET /me/notification-preferences` | signed in | `{ conversationEmails: bool, emailsEnabled: bool }` (`emailsEnabled` = the kill switch) |
| `PUT /me/notification-preferences` | signed in | body `{ conversationEmails: bool }` → same shape; upsert by `sub` |
| `GET /me/watched-groups` | full-scope audience, else 403 | `{ items: [{ smallGroupId, name, closed, watching }] }`, every group, open first then by name |
| `PUT /small-groups/{id}/watch` | full-scope audience, else 403; unknown group 404 | body `{ watching: bool }` → `{ smallGroupId, watching }`; deletes or inserts the opt-out |

"Full-scope audience" is the same shared check: a full scope from `small_group_scope_for` and
`can_read_group_conversations` true. The routes work while emails are off (staff-app hides them).

**Docs:** `docs/ARCHITECTURE.md` (the outbox, the consumer/`notifications/` boundary, claiming and
outcomes, the worker and its two ways to run, the settings, the routes), one line in `CLAUDE.md`,
`.env.example`.

**End-to-end hand-check** (the spec's list; emails only to Luis's test accounts):

- [ ] An elder starts a thread → the group's leader gets the email (the main case).
- [ ] A leader starts a thread → every watching elder gets one email; an elder who unwatched doesn't,
      unless they commented.
- [ ] Two leaders reply at the same moment → one email.
- [ ] A leader who stepped down, or whose role lost `smallGroupReports: view`, gets nothing.
- [ ] A comment deleted before processing → no email.
- [ ] The user opens the thread before the worker runs → no email.
- [ ] After *Mark all read*, the next leader comment → an email; the same after the newest comment
      (the one emailed about) was deleted before *Mark all read*.
- [ ] An email link to a guest's row opens that guest's panel (and `?person=`, `?section=`).
- [ ] Kill the worker mid-batch → no duplicate email, `attempts` went up.
- [ ] auth-server down for 2 hours → nothing goes `dead`, everything sends once it's back.
- [ ] auth-server up but Resend returning 503 for 2 hours → the same.
- [ ] A wrong internal token, or the route not deployed (bare 404) → retries, an error logged,
      nothing `dead`.
- [ ] An email queued, then "Conversation emails" turned off before it sends → `suppressed`.
- [ ] A batch with more than 500 candidates → permissions fetched in chunks, nobody dropped.
- [ ] A processing exception → `failed` with `last_error` set.
- [ ] An event older than 24 h → `expired`.
- [ ] An event processed 23 h after its comment whose send keeps failing → the delivery expires at
      the comment's 24 h mark, not 24 h later.

Then mark this log done and update the cross-repo spec only where the build differs.

## Not in this handoff

- Push notifications (another `channel` on deliveries and preferences; `outbox_events` unchanged).
- Digests, an admin view of `dead` rows (query the tables), relaying events to SQS/EventBridge,
  waking a separate worker with `LISTEN/NOTIFY`.
- The ECS task definition for a separate worker and the Phase 9 alarms (`management-infra`).
