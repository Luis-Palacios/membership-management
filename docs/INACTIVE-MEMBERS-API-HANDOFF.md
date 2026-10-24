# Inactive members: status, deactivate / reactivate, and keeping them out

Handoff spec for the membership-management side of **inactive members**. Read the cross-repo spec
first: `../docs/specs/inactive-members.md` (workspace folder `members-management/docs/specs/`). Its
rules are referred to as *rule N*, and its *Schema* and *Contracts* sections are the target. It
builds on member-user linking, leader access, roles and permissions, and guest small groups (all on
`main`).

What this adds:

- `members.status` (`active` | `inactive`) and an append-only `member_status_changes` table (rules
  1–3).
- `POST /members/{id}/deactivate`, `POST /members/{id}/reactivate`,
  `GET /members/{id}/status-history`, behind `members: setStatus` (rules 4–8, 10).
- Inactive members filtered out of lists, pickers, group membership, linking and counts (rule 11).

Work through it **stage by stage**, one reviewable commit per stage, on the **`inactive-members`**
branch (the same name in every repo).

- **Checks.** Each stage must pass `uv run ruff check .` and `uv run ty check` (and
  `uv run alembic check` in stage 1).
- **Roles to try.** Try each stage against the local API (`TestClient` with the claims dependency
  overridden, as before) as each role:
  - `admin`
  - `elder`, linked and unlinked
  - `smallGroupLeader` leading the member's group
  - `deacon` with no member
  - `user`
- **No test runner yet,** so note in *Decisions and deviations* what you tried and how.
- **Don't touch the dev database:** use a scratch one, as in the guest small groups work.

**Depends on:** auth-server stage 1 (`auth-server/docs/INACTIVE-MEMBERS-HANDOFF.md`):
`members: setStatus` must be in the JWT before stage 2 can be tried as a real role. If it isn't there
yet, say so and stop at the end of stage 1. Don't stub permissions in committed code.

Keep the existing conventions:
- Routes call `services.py` directly; `queries.py` builds `Select`s; `results.py` holds `NamedTuple`s
  mapped with `all_as`.
- Schemas are `CamelModel`.
- Service errors are domain exceptions the router maps to HTTP codes.
- "Today" is `church_today()`.
- Routes doing blocking database work stay plain `def`.
- Enums are VARCHAR + CHECK.
- The new code lives in the `data/members/` domain.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration, models, seed | ✅ | 2208a5a |
| 2. Deactivate, reactivate, history | ✅ | 438f306 |
| 3. Keeping inactive members out | ✅ | 614d4cb |
| 4. Docs | ✅ | this commit |

### Decisions and deviations

All stages were tried against the scratch database `ima-scratch` (never the dev one), with a
`TestClient` and `get_current_claims` overridden per role. The permission sets copy
`auth-server/src/permissions/statements.ts` on its `inactive-members` branch, where `setStatus` is
already present. One slip: a final `uv run alembic check` ran without the scratch URL and read the dev
DB (read-only; it only reported "not up to date").

**Stage 1.**
- `alembic upgrade head`, `alembic check`, `downgrade -1` and `upgrade head` round-trip on the scratch DB.
- The downgrade refuses (`RuntimeError`) once a `member_inactive` period exists.
- Seeded with the old code and again with the new: members 1-55, group periods, reports, attendances and
  guests are byte-identical (compared column by column). The new rows are members 56-58, added by
  `seed_inactive_members` (last in `SEEDERS`): 56 left, came back and left again (linked to
  `seed-user-inactive-1`), 57 transferred, 58 deceased.
- The `status` CHECK is also on `member_status_changes` (the spec lists it as VARCHAR(10) only).

**Stage 2.** 39 checks in a scratch script, as `admin`, `elder` (linked and unlinked), `smallGroupLeader`
(linked, leading the group), `deacon` and `user`:
- Leader, deacon and user get 403 on all three routes. A leader of an open group gets 409 `leads_group`
  with `groups` and nothing changes (no history row). A co-leader is removed from the group.
- `left_at` is today (Managua) while `effective_date` stays as sent. Reactivating leaves groups closed.
- Repeats give `already_inactive` / `already_active`. Self gives `self`. A future date, a note over 1000
  characters and an unknown reason give 422. A blank note is stored as null.
- A user viewing their own inactive member sees the status and `inactiveSince` but a null reason and note,
  and gets 403 on the history. A leader gets 404 for a former member who is now inactive.
- The history is newest first, and `changedByName` is the linked member's name or null.
- `pastSmallGroups` is the `member_inactive` periods with the latest `left_at`, as long as that is on or
  after the day of the latest deactivation (no timezone maths). First built without that last check,
  which showed an earlier deactivation's groups after a second one that ended none; fixed in
  `88eb92b`. What remains: deactivated, reactivated and deactivated again **on the same day** with
  no group joined in between still shows the first period, since both end that day. That only
  happens within one day.
- `CodedHTTPError` (`api/coded_errors.py`) and one handler in `main.py` produce the 409 bodies
  `{detail, code, ...extra}`; stage 3 reuses it.
- `member_detail` now takes the caller's claims (to decide who sees the reason and note), so `PATCH
  /me/member` and the other callers pass them.

## Stage 1: migration, models, seed

- `Member` gains `status: Mapped[MemberStatus]` (`StrEnum`: `active`, `inactive`). Use VARCHAR(10) +
  CHECK, `server_default='active'`, NOT NULL, the same `Enum(..., native_enum=False,
  create_constraint=True, values_callable=...)` pattern as `sex`. Also add
  `status_changed_at: Mapped[datetime | None]` (timestamptz).
- New model `MemberStatusChange` in `data/members/models/` (import it in `data/models.py`), per the
  spec's *Schema*:
  - `reason` is a `MemberInactiveReason` StrEnum with six values, VARCHAR(20) + CHECK.
  - A table CHECK `(status = 'inactive') = (reason IS NOT NULL)`.
  - Index `(member_id, created_at DESC)`.
  - `changed_by_user_id` is a plain string (no FK, separate databases).
- `LeftReason` gains `MEMBER_INACTIVE = "member_inactive"`. Update its docstring: set only by
  deactivation (rule 6). The schema `SmallGroupMemberRemoveSchema` (or whichever body accepts
  `left_reason` today) must **not** accept it: only `STOPPED_COMING` and `OTHER` stay allowed from
  the API.
- Migration:
  - add the columns (existing rows become `active`);
  - create the table;
  - extend the `left_reason` CHECK.
  - Downgrade drops the table and columns, and fails loudly if any `left_reason = 'member_inactive'`
    rows exist, rather than silently rewriting history.
- Seed: two or three inactive members with a history (one who left and came back, as on the
  `MemberDetail-Inactive` board). Their periods are closed with `member_inactive`, and one of them is
  linked to a user. Keep every other seeded row identical, so a before/after dump of the GET routes
  only differs by the new fields and those members.

## Stage 2: deactivate, reactivate, history

Services in `data/members/services.py`. The router maps domain errors to the codes in the spec's
*Contracts*. 409 bodies are `{"detail": "<message>", "code": "<code>"}`, plus `groups` for
`leads_group`; check how existing HTTPExceptions are raised and keep `detail` a readable sentence.

**`deactivate_member(session, member, *, reason, effective_date, note, changed_by_user_id, today)`**,
in one transaction:

1. Lock the member row (`with_for_update`).
2. Raise `MemberAlreadyInactiveError` if already inactive.
3. Raise `MemberLeadsGroupError(groups)` if `member_active_leads_query` (or equivalent) finds open
   groups where they're the `leader` (rule 7, member and guest groups).
4. `effective_date > today` → 422.
5. Close every open period (`left_at IS NULL`) with `left_at = today`,
   `left_reason = MEMBER_INACTIVE` (rule 6). Reuse whatever closing helper group close or remove
   uses, so the period-closing logic lives in one place.
6. Insert the change row, set `status` and `status_changed_at`.

**`reactivate_member(...)`**: lock, raise `MemberAlreadyActiveError`, insert
`(status=active, reason=None, effective_date=today)`, update the member. **Don't** touch group
periods (rule 10).

**Routes** (both `members: setStatus`, rate-limited like `link_member_user`):

- `POST /members/{member_id}/deactivate`
  - Body `MemberDeactivateSchema { reason, effectiveDate, note? }`.
  - The note is trimmed, empty becomes `None`, max 1000 characters.
  - If `member.user_id == claims.sub`, return 409 `self` (rule 8), checked before the service.
  - Returns `MemberDetailSchema`.
- `POST /members/{member_id}/reactivate`
  - Body `{ note? }`.
  - Returns `MemberDetailSchema`.
- `GET /members/{member_id}/status-history`
  - Newest first.
  - `changedByName` is the name of the member whose `user_id` is `changed_by_user_id`, or `null`.

**Schema additions** (rule 5):

- `MemberDetailSchema` gains:
  - `status`
  - `inactiveSince` (the latest change's `effectiveDate` when inactive, else `null`)
  - `inactiveReason`, `inactiveNote`: filled only when the caller has `members: setStatus`
  - `pastSmallGroups`: the periods closed by the latest deactivation, i.e. `left_reason =
    member_inactive` and `left_at` = that change's date. Same shape as current groups plus
    `leftAt`. Empty when active.
- The caller's own member (*permissions rule 10*) gets the same treatment: they see their status,
  not the reason, unless they have `setStatus`.

**Try:**

- admin and elder can deactivate and reactivate.
- Leader, deacon and user get 403.
- A leader of an open group gets 409 `leads_group` with the group list, and nothing changes.
- A co-leader is removed from the group.
- The member's periods close with today's date while `effectiveDate` stays as sent.
- Reactivating leaves groups closed.
- Repeating either call gives the matching 409.
- The history shows both entries.
- A non-`setStatus` caller who can see the member gets `null` reason and note, and 403 on history.

## Stage 3: keeping inactive members out (rule 11)

- `GET /members`:
  - Optional `status` query (`active` default, `inactive`, `all`; anything else 422).
  - `MemberSummarySchema` gains `status`, `inactiveSince`, and `inactiveReason` (null without
    `setStatus`).
  - Change `list_members_query` to take the status. Don't add a second query.
- `GET /members/options` (`member_options_query`): active only, no parameter.
- `GET /members/search`: rows gain `status`. Full-scope callers still find inactive members; scoped
  callers can't, because scope already requires an open period.
- `add_small_group_member` and the role-change path: raise `MemberInactiveError` → 409
  `member_inactive`. Check it in the service, so every caller is covered.
- `link_member_user` → 409 `member_inactive`. Invites from a member are created by auth-server, so
  the guard there is staff-app hiding the action, plus the next point.
- `link_member_by_accepted_invite`: skip inactive members (no link, same return as "no match"), and
  log it at info.
- Counts: grep for every query that counts or lists members for a dashboard or report header, and
  make them count active members. List what you changed in the log.
- **Leave alone:**
  - report rosters and attendance (they come from periods, which are already closed);
  - conversations;
  - prayer & follow-up;
  - `GET /members/{id}` for full-scope callers (they must open inactive members).

**Try:**

- The default list has no inactive members; `status=inactive` and `status=all` behave as named.
- `options` never returns inactive members.
- Each 409 path returns `member_inactive`.
- An accepted invite matching an inactive member's email links nothing.
- A leader gets 404 for a former member of their group who is now inactive.
- Dump every GET route for every role before and after, and explain each difference.

## Stage 4: docs

- `docs/ARCHITECTURE.md`: the three new routes in the role × route table, and the `status` query on
  `GET /members`.
- A short note under the members domain: what status means and that `member_inactive` periods are
  written only by deactivation.
- Tick the stages here. Mention in your final message anything staff-app must pick up (new fields
  and codes).
