# Notifications, Part 1: in-app list (membership-management)

Handoff for the API side of the **in-app notification list**: every notification the three
consumers already email (conversation comments, submitted reports, weekly report reminders) also
becomes one `user_notifications` row per recipient, listed by `GET /me/notifications`, counted by
`GET /me/notifications/unread-count`, marked read by two POST routes, auto-read by opening a thread
(rule 13) or submitting a report (rule 14), and purged after 90 days. Outbox, worker, claiming,
`notifications/` and preferences are the email work's, reused as built. **Nothing from Part 2
(push).**

- Rules and contracts: `../docs/specs/notifications.md` (*rule N*), Part 1 step 1 and *Contracts
  (Part 1: in-app) → membership-management*.
- Extends `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`, `docs/REPORT-SUBMITTED-EMAILS-API-HANDOFF.md`,
  `docs/REPORT-REMINDER-EMAILS-API-HANDOFF.md` and `docs/ARCHITECTURE.md`, *Report conversations, Part 2*.
- staff-app (after this repo is merged): `../staff-app/docs/design/NOTIFICATIONS.md`.

Branch **`feature/notifications`**. Each stage: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run ty check`, `uv run python -m unittest discover -s tests`, `uv run alembic check`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| Handoff written | ✅ | `cc87bd2` |
| 1. `user_notifications` table + model + migration `ea20b44459b8`; `IN_APP_NOTIFICATIONS_ENABLED` flag | ✅ | `6d76fa2` |
| 2. `create_entries` in `notifications/`; the three consumers write entries | ✅ | `e8eef34` |
| 3. Routes + schemas (`GET /me/notifications`, `/unread-count`, `POST /{id}/read`, `/read-all`) | ⬜ | |
| 4. Rule 13 and rule 14 read side effects | ⬜ | |
| 5. 90-day purge; `docs/ARCHITECTURE.md`, `.env.example`, `CLAUDE.md` | ⬜ | |

## Plan per stage

1. **Table, model, flag.** `data/notifications/models/user_notification.py` with the spec's columns
   (`id` bigint identity, `user_id`, `source_event_id`, `category`, `template`, `data` jsonb, `path`,
   `subject_key`, `small_group_ids` int[] null, `created_at`, `read_at`), unique
   `(source_event_id, user_id)`, indexes `(user_id, id desc)`, partial `(user_id) where read_at is
   null`, `(subject_key)`. Registered through the existing `data/notifications/models/__init__.py`
   (`data/models.py` already imports the package). `NotificationSettings.in_app_notifications_enabled`
   (`IN_APP_NOTIFICATIONS_ENABLED`, default false).
2. **Writing.** `notifications/entries.py`: `EntryRequest` + `create_entries(session, source_event_id,
   requests)` (`insert ... on conflict do nothing` on `(source_event_id, user_id)`), generic: knows
   categories and templates, never conversations. No preference filter (rule 2). Each consumer calls it
   with the **same recipients** it passes to `create_deliveries`, built from the same
   `template` / `data` / `path`, while its kind flag AND the in-app flag are on (rule 3).
3. **Routes.** In `api/routers/me.py`, schemas in `api/schemas/notifications.py`, camelCase.
4. **Read side effects.** Rule 13 in `mark_read` and `mark_all_read`; rule 14 in the submit
   transactions.
5. **Purge and docs.**

## Decisions and deviations

(Filled in as the stages land.)
