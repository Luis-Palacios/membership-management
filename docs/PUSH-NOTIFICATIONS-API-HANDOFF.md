# Notifications, Part 2: push (membership-management)

Handoff for the API side of **Web Push**: every notification the three consumers already email and
list in-app also becomes one `channel = "push"` delivery per recipient, whose payload auth-server fans
out to the recipient's devices. Adds the `PUSH_NOTIFICATIONS_ENABLED` flag, `create_entries` returning
the inserted entry ids and the recipient's unread count (the push's `notificationId` and `badgeCount`),
the sender's `no_push_subscription` mapping, and the push switches in the preferences routes. Outbox,
worker, claiming, deliveries and preferences are the email work's, reused as built.

- Rules and contracts: `../docs/specs/notifications.md` (*rule N*), Part 2 step 4, rules 1, 3, 5, 19,
  20, 24, *Contracts (Part 2: push) → membership-management* and *Sender mapping in
  membership-management*.
- Extends `docs/NOTIFICATIONS-API-HANDOFF.md` (Part 1, merged) and the three email handoffs.
- Built in parallel with auth-server (`../auth-server/docs/PUSH-NOTIFICATIONS-HANDOFF.md`); the
  contract between them is fixed by the spec. staff-app (after both are merged):
  `../staff-app/docs/design/PUSH-NOTIFICATIONS.md`.

Branch **`feature/notifications-push`**. Each stage: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run ty check`, `uv run python -m unittest discover -s tests`, `uv run alembic check`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| Handoff written | ✅ | `e8e69d0` |
| 1. `PUSH_NOTIFICATIONS_ENABLED` flag + config (token rule, `.env.example`) | ✅ | `37b1eac` |
| 2. `create_entries` returns the id and unread count per user | ✅ | `fdb503b` |
| 3. A `push` request per recipient in the three consumers | ⬜ | |
| 4. Sender: 404 `no_push_subscription` → `dead` (info) | ⬜ | |
| 5. Preferences routes (`push`, `availablePush`); `docs/ARCHITECTURE.md`, `CLAUDE.md` | ⬜ | |

## Plan per stage

1. **Flag.** `NotificationSettings.push_notifications_enabled` (`PUSH_NOTIFICATIONS_ENABLED`, default
   false). Like the kind flags it needs `INTERNAL_API_TOKEN` (auth-server is called for every push).
   Push works for a kind only while the kind's flag AND this one are on (rule 3). Push needs the
   worker and auth-server calls, but it can only ever matter while a kind flag is on, and every kind
   flag already makes `any_emails_enabled` / `worker_enabled` true, so those two properties need no
   change and no rename.
2. **Entries.** `create_entries` returns `dict[user_id, EntryResult(notification_id, unread)]` for
   every requested user. It uses `on conflict do nothing`, so on a retried event the row already exists:
   the missing ids are read back by `(source_event_id, user_id)`. `unread` is the user's unread count
   after the insert, in the same transaction (so it includes the entry).
3. **Consumers.** Generic helper `notifications/push.py` turns the email `NotificationRequest`s into
   push ones (same template, data and path; payload adds `channel`, `notificationId`, `badgeCount`),
   so the consumers keep no push logic of their own beyond the gate. `notificationId` is null and
   `badgeCount` 0 while in-app is off (no entry exists, so nothing is unread).
   `create_deliveries` already filters by `(user, category, channel)` and is unique per
   `(event, user, channel)`: push rows sit next to the email rows.
4. **Sender.** `_send_outcome`: 404 + `no_push_subscription` → `SendOutcome("dead", …)`, logged at info.
   Checked that `sending.py` and the claim path never look at the channel except `is_enabled(...,
   delivery.channel)`, which is right for push.
5. **Preferences.** `push` and `availablePush` on GET; `push` (any subset) on PUT, `email` now optional.
   No migration: `channel` is a plain `String(16)` and `notification_preferences` has no check on it.

## Decisions and deviations

(filled in as the stages land)
