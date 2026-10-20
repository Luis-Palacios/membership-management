# Small group reports: conversations (Part 1, no email)

Handoff spec for the membership-management side of **report conversations**: elders and admins
start a thread about one person's attendance row in a small group report, the group's leaders
reply, and threads can be resolved. Cross-repo rules: `../docs/specs/report-conversations.md`
(*rule N* below). The staff-app side is `staff-app/docs/design/REPORT-CONVERSATIONS.md`; design
boards: [Staff App canvas](https://claude.ai/artifact/PLs9gdHVcigkRSAWJrsKs1), page
"Report conversations".

**This is Part 1 only.** Nothing here sends email, calls auth-server, or creates outbox rows. Part 2
(email) gets its own handoff after this is on `main`, and is worked one change at a time.

**Decided (don't re-open):**

- One thread per `(report_id, member_id)`; the member must have an attendance row on the report.
- Audience = rule 9 of the reports spec: `observations_visible_to(sees_all_observations,
  leads_group)` and the report inside the caller's `SmallGroupScope`. No new permission.
- Commenting needs a linked member (`get_current_member`), 409 otherwise. Reading doesn't.
- Comments are plain text, 1–4000 chars after trimming. Edit and soft-delete your own only.
- `open` / `resolved`; any participant resolves or reopens; a new comment reopens.
- Closed groups: reports read-only, conversations writable (rule 13).
- Deleting a report deletes its conversations (FK cascade).

Work through it **stage by stage**, one reviewable commit per stage, on the
**`report-conversations`** branch (same name in staff-app). Each stage must pass
`uv run ruff check .` and `uv run ty check`, and be tried against the local API as: admin, elder
linked, elder **unlinked**, leader in scope, co-leader in scope, leader of another group, former
leader, leader of a closed group, deacon, user. Keep the conventions of the reports handoff
(services / queries / results split, `CamelModel`, domain errors mapped in a router `_http_error`,
`church_today()` where dates matter, plain `def` routes, per-route `rate_limit`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration and models | ✅ | (this commit) |
| 2. Reads: per-report summaries, one thread, mark read | ⬜ | |
| 3. Writes: comment, edit, delete, resolve, reopen | ⬜ | |
| 4. Inbox and counts | ⬜ | |
| 5. Report delete count, seed and docs | ⬜ | |

### Decisions and deviations

- Stage 1: the handoff file was already committed on `main` (`0abf7f0`), not untracked, so there is no
  separate first commit; the branch starts at Stage 1.
- Stage 1: table and model names are as in the handoff; `status` and `side` are VARCHAR + hand-written
  CHECK (no native enum), typed in code as `ConversationStatus` / `ConversationSide` Literals.
- Stage 1: the resolved-columns CHECK is written as "open with all three NULL, or resolved with all
  three set". The unique `(report_id, member_id)` constraint gets the convention name
  `uq_report_conversations_report_id` (the naming convention only uses the first column).
- Stage 1: migration `dadaa792d43d`. Upgrade, `downgrade -1`, upgrade and `alembic check` are clean.
  `ReportConversation.last_comment_*` and the `created_at`/`*_at` columns have no server default; the
  service sets them from one `now()` per transaction.

## Data model

New models in `data/small_groups/models/` (one file per model, like the others). Table names may
change if they read better; record it under *Decisions*.

### `report_conversations`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | identity PK | |
| `report_id` | FK `small_group_reports.id` **ON DELETE CASCADE**, indexed | |
| `member_id` | FK `members.id`, indexed | The attendance row's member |
| `status` | `VARCHAR(16) NOT NULL` | `open` \| `resolved` (CHECK) |
| `created_by_user_id` | `VARCHAR NOT NULL` | JWT `sub`, no FK (auth-server user) |
| `created_at` | `timestamptz NOT NULL` | |
| `resolved_by_user_id` | `VARCHAR NULL` | |
| `resolved_by_member_id` | FK `members.id` NULL | For the name in "Resolved by …" |
| `resolved_at` | `timestamptz NULL` | CHECK: both resolved columns set iff `status = 'resolved'` |
| `last_comment_at` | `timestamptz NOT NULL` | Denormalised; newest non-deleted comment |
| `last_comment_side` | `VARCHAR(8) NOT NULL` | `elders` \| `leaders` (CHECK) |
| `last_comment_user_id` | `VARCHAR NOT NULL` | For unread ("by someone else") |

Unique `(report_id, member_id)`. Index `(last_comment_at DESC)` for the inbox.

### `report_conversation_comments`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | identity PK | |
| `conversation_id` | FK **ON DELETE CASCADE**, indexed | |
| `author_user_id` | `VARCHAR NOT NULL` | |
| `author_member_id` | FK `members.id` NOT NULL | Rule 5: always linked |
| `side` | `VARCHAR(8) NOT NULL` | Rule 6, fixed at write time |
| `body` | `TEXT NOT NULL` | Kept on soft delete, never returned |
| `created_at` | `timestamptz NOT NULL` | |
| `edited_at` | `timestamptz NULL` | |
| `deleted_at` | `timestamptz NULL` | |

### `report_conversation_comment_revisions`

`id`, `comment_id` FK ON DELETE CASCADE, `body TEXT NOT NULL`, `replaced_at timestamptz NOT NULL`.
Written on every edit with the **previous** body. Never exposed by the API.

### `report_conversation_reads`

PK `(user_id VARCHAR, conversation_id FK ON DELETE CASCADE)`, `last_read_at timestamptz NOT NULL`.

**Side** (rule 6): `elders` when the author's claims have `smallGroups: all`, else `leaders`.
A helper `comment_side(claims) -> Side` in `api/access.py`.

**Denormalised fields** are maintained by the service on every comment insert, edit (no change to
`last_comment_at`) and delete (recompute from the newest non-deleted comment; a thread whose
comments are all deleted keeps its row and shows only stubs).

## Access (one helper, used by every route)

```python
def conversation_access(report, claims, scope) -> None:
    # 404 if the report's group is outside scope (same as report detail)
    # 403 if not observations_visible_to(sees_all_observations=_sees_all_observations(claims),
    #                                    leads_group=_leads_group(scope, report.small_group_id))
```

Reuse `_sees_all_observations` / `_leads_group` from the reports router (move them to
`api/access.py` if two routers need them; note it). Writes additionally need `get_current_member`
(409, rule 5). Edit and delete also need `comment.author_user_id == claims.sub` (403
`"That's not your comment."`).

## Routes and shapes (camelCase)

### `GET /small-group-reports/{id}/conversations`

Row indicators and the section summary. Empty list when the report is a no meeting.

```jsonc
{
  "conversations": [
    { "id": 41, "anchor": { "type": "attendance", "memberId": 1207 }, "status": "open",
      "commentCount": 3, "unread": true, "needsMyReply": true, "lastCommentAt": "2026-10-15T13:02:00Z" }
  ],
  "counts": { "total": 3, "needsMyReply": 1 }
}
```

- `commentCount` excludes deleted comments.
- `unread`: `last_comment_user_id != sub` and (`last_read_at` missing or `< last_comment_at`).
- `needsMyReply`: `status = open` and `last_comment_side != comment_side(claims)`.

### `GET /small-group-reports/{id}/conversations/{memberId}`

404 `"No conversation yet."` when no thread (the staff app shows the empty panel; tell it apart by
`detail`). 422 `attendance` when the member isn't on the report.

```jsonc
{
  "id": 41, "anchor": { "type": "attendance", "memberId": 1207 }, "status": "resolved",
  "resolvedBy": { "memberId": 88, "name": "Samuel Ortega" }, "resolvedAt": "2026-10-13T00:40:00Z",
  "firstUnreadCommentId": null,
  "comments": [
    { "id": 301, "author": { "memberId": 12, "name": "Roberto Aguilar", "side": "elders" },
      "body": "…", "createdAt": "…", "editedAt": null, "deleted": false, "mine": true },
    { "id": 302, "author": { "memberId": 7, "name": "Carlos Mendoza", "side": "leaders" },
      "body": null, "createdAt": "…", "editedAt": null, "deleted": true, "mine": false }
  ]
}
```

Comments oldest first. `firstUnreadCommentId` = the first comment by someone else after your
`last_read_at` (null if none). Does **not** mark read.

### `POST /small-group-reports/{id}/conversations/{memberId}/comments`

Body `{ "body": "…" }`. Creates the thread when missing, reopens it when resolved (clears the
resolved columns), inserts the comment, updates the denormalised fields, and marks the thread read
for the author, all in one transaction. Returns the full thread (shape above), **201**.
Race on creating the thread (unique violation) → retry once inside the service, then 409.

### `PATCH /report-conversation-comments/{id}` · `DELETE /report-conversation-comments/{id}`

PATCH body `{ "body": "…" }`: writes a revision with the old body, sets `edited_at`. Editing a
deleted comment → 409 `"deleted"`. DELETE sets `deleted_at` (idempotent), recomputes the
denormalised fields. Both return the full thread.

### `POST /report-conversations/{id}/resolve` · `/reopen`

Idempotent. Resolve needs a linked member (to store the name), 409 otherwise. Return the thread.

### `POST /report-conversations/{id}/read`

Upsert `last_read_at = now()`. 204.

### `GET /report-conversations?tab=reply|open|resolved&smallGroupId=&limit=&offset=`

The inbox. Scope: `smallGroups: all` + `viewObservations` → every group; otherwise the scope's
`group_ids` (former leaders see nothing, closed-group leaders see their closed group). `tab=open`
includes `reply`. Newest `last_comment_at` first; default `limit` 25, max 50.

```jsonc
{
  "items": [
    { "id": 41, "status": "open", "needsMyReply": true, "unread": true,
      "member": { "id": 1207, "name": "Daniela Rojas" },
      "group": { "id": 3, "name": "Jóvenes Bello Horizonte", "closed": false },
      "report": { "id": 812, "meetingDate": "2026-10-08" },
      "lastComment": { "authorName": "Andrea Gutiérrez", "mine": false, "deleted": false,
                       "excerpt": "I told her you’re coming on Saturday…", "createdAt": "…" },
      "resolvedBy": null, "commentCount": 3 }
  ],
  "counts": { "reply": 3, "open": 5, "resolved": 3 },
  "total": 3
}
```

- `excerpt`: first 160 chars of the newest non-deleted comment, whitespace collapsed. For
  `resolved` rows the client shows "Resolved by …" from `resolvedBy` plus the excerpt.
- `counts` ignore `smallGroupId` only if that's simpler; say which under *Decisions*.

### `GET /report-conversations/counts`

`{ "needsMyReply": 3 }`. Called on every page for the sidebar badge, so one indexed query. Users
outside the audience get `0` (not 403), so the staff app can call it without checking first.

### Report detail and delete

`ReportDetailSchema` gains `conversationCount: int` (threads on the report) for the delete
dialog ("This also deletes 3 conversations."). Delete itself is unchanged; the cascade does it.

## Errors

| When | HTTP | detail contains |
| --- | --- | --- |
| Group outside scope | 404 | (same as report detail) |
| Can't see observations | 403 | `permission` |
| No linked member on a write | 409 | `Link your account to a member to comment.` |
| Member not on the report / no-meeting report | 422 | `attendance` |
| Thread missing on GET | 404 | `No conversation yet` |
| Empty or > 4000 body | 422 | Pydantic |
| Edit/delete someone else's comment | 403 | `not your comment` |
| Edit a deleted comment | 409 | `deleted` |

## Stage 1: Migration and models

- The four models above, relationships (`SmallGroupReport.conversations` with
  `cascade="all, delete-orphan", passive_deletes=True`), CHECKs written by hand.
- `uv run alembic revision --autogenerate -m "add report conversations"`; review; `upgrade head`,
  `downgrade -1`, `upgrade head`; `alembic check` clean.
- Results tuples for thread, comment, summary and inbox row in `results.py`.

## Stage 2: Reads

- `conversation_access` + `comment_side` in `api/access.py`.
- Queries: summaries for a report (joined with the caller's reads), one thread with its comments
  and author names (`members` join), resolved-by name.
- Routes: report summaries, one thread, mark read. Try every role from the list above; a former
  leader must get 404, a leader of another group 404, a user 403.

## Stage 3: Writes

- Service functions: `add_comment`, `edit_comment`, `delete_comment`, `resolve`, `reopen`; each
  keeps the denormalised fields right. Unit-test the recompute after deleting the newest comment.
- Rate limits: comment 30/minute, edit 30/minute, delete 20/minute, resolve/reopen 30/minute.
- Check: comment on a closed group's report works; an unlinked elder can read but gets 409 on
  every write; a new comment on a resolved thread reopens it.

## Stage 4: Inbox and counts

- One query for the inbox rows (thread + report + group + member + newest non-deleted comment via
  `DISTINCT ON` or a lateral join) and one for the counts. `EXPLAIN` both with the seed data and
  note the plan in *Decisions*.
- `counts` endpoint uses the same filters, `COUNT(*)` only.

## Stage 5: Report delete count, seed and docs

- `conversationCount` on report detail.
- Seed: a handful of threads on recent reports across groups, every state (needs reply each side,
  open waiting, resolved, one with an edited and a deleted comment), in Spanish, using the seed's
  existing elders and leaders.
- `docs/ARCHITECTURE.md`: route table rows and the role × route table; one line in `CLAUDE.md`.
  Mark this log done; fix the cross-repo spec only if the build had to differ.

## Not in this spec

- Email notifications (Part 2: outbox, `BackgroundTasks`, sweeper, opt-out).
- Threads on report sections; member conversation history; @mentions; moderation.
