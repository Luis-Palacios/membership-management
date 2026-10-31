# Inactive guests and status on the timeline

Handoff spec for the membership-management side of **inactive guests** and **status changes on the
person timeline**. Read the cross-repo spec first: `../docs/specs/inactive-guests.md` (workspace
folder `members-management/docs/specs/`). Its rules are referred to as *rule N* and its *Contracts*
section is the target. It builds on inactive members (`INACTIVE-MEMBERS-API-HANDOFF.md`), guest
small groups (`GUEST-SMALL-GROUPS-API-HANDOFF.md`) and the person timeline
(`REPORT-TAGS-API-HANDOFF.md`, Part 2), all on `main`.

What this adds:

- `guests.status` (`active` | `inactive`) and an append-only `guest_status_changes` table (rules 1–3).
- `POST /guests/{id}/deactivate` and `POST /guests/{id}/reactivate` (rules 4–6), and
  reactivate-and-add on `POST /small-groups/{id}/guests` (rule 6).
- Inactive guests kept out of the tag picker, with `status` on every guest row and search result
  (rules 7–10).
- The person timeline as **typed entries**, with status entries for members and guests (rules
  12–15), shipped expand / contract.

Work through it **stage by stage**, one reviewable commit per stage, on the **`inactive-guests`**
branch (the same name in every repo).

- **Checks.** Each stage must pass `uv run ruff check .` and `uv run ty check` (and
  `uv run alembic check` in stage 1).
- **Roles to try.** Try each stage against the local API (`TestClient` with the claims dependency
  overridden, as before) as each role, with `GUEST_GROUPS_ENABLED` on:
  - `admin`
  - `elder`, linked and unlinked
  - `smallGroupLeader` leading a guest group, and one leading only member groups
  - `deacon` with no member
  - `user`
- **No test runner yet,** so note in *Decisions and deviations* what you tried and how.
- **Don't touch the dev database:** use a scratch one, as in the inactive members work.

**Depends on:** auth-server stage 1 (`auth-server/docs/INACTIVE-GUESTS-HANDOFF.md`):
`guests: deactivate` and `guests: reactivate` must be in the JWT before stage 2 can be tried as a real
role. If they aren't there yet, say so and stop at the end of stage 1. Don't stub permissions in
committed code. **Stage 5 waits for staff-app** to deploy the stage that reads `entries`.

Keep the existing conventions:
- Routes call `services.py` directly; `queries.py` builds `Select`s; `results.py` holds `NamedTuple`s
  mapped with `all_as`.
- Schemas are `CamelModel`.
- Service errors are domain exceptions the router maps to HTTP codes; 409s with a `code` go through
  `CodedHTTPError` (`api/coded_errors.py`).
- "Today" is `church_today()`.
- Routes doing blocking database work stay plain `def`.
- Enums are VARCHAR + CHECK.
- Guest status code lives in the `data/guests/` domain, next to the member status code it mirrors
  (`data/members/models/member_status_change.py`, `deactivate_member` / `reactivate_member`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Migration, models, seed | ✅ | `cea573d` |
| 2. Deactivate, reactivate, status on guests | ✅ | `6e67779` |
| 3. Reactivate and add | ✅ | `efd6509` |
| 4. Timeline entries (expand) | ✅ | `079aaaf` |
| 5. Timeline entries (contract): drop `rows` | ⬜ waits for staff-app stage 5 to be deployed | |
| 6. Docs | ✅ | see `git log` |

### Decisions and deviations

All stages were tried on the scratch database `ig-scratch` (never the dev one), with a `TestClient` and
`get_current_claims` overridden per role, `GUEST_GROUPS_ENABLED` on. The permission sets copy
`auth-server/src/permissions/statements.ts` on its `inactive-guests` branch (`ddd736c`, not on its `main`
yet); no real JWT was used.

**Stage 1.** `upgrade`, `alembic check`, `downgrade -1` and `upgrade` round-trip. Existing guests became
`active` with no history. Reseeding and diffing every table: all 885 earlier rows unchanged, 13 added.
Downgrade refuses once `guest_inactive` periods exist. No member change in the seed: Ernesto Ordóñez
already has both kinds of status entry.

**Stage 2.** Scripted as every role on the list: everything under *Try*, plus blank notes, the remove body
refusing `guest_inactive`, and tag rules on `PATCH /small-group-reports/{id}`. One case the *Try* list
doesn't name: an inactive guest already tagged in one section can't be newly tagged in another, as for
members.

**Stage 3.** Scripted, including the rollback when the join date overlaps or is in the future (still
inactive, no history row). A role with `manageMembers` but no `guests: reactivate` doesn't exist today, so
that 403 used a made-up permission set.

**Stage 4.** Dumped the timeline before and after for all 8 role variants × every seeded member and guest ×
6 parameter sets (3,504 responses): status codes, `rows`, `counts`, `groups`, `person`, `from`, `to`
byte-identical; `earliestDate` moved older in 96, all people whose oldest entry is a status change. The
rest of *Try* scripted, including ties and the OpenAPI discriminator.

Not tried: the row locks under real concurrency.

Decisions:

- **`effectiveDate`, not `leftOn`.** The cross-repo spec's *Contracts* says `{ reason, leftOn?, note? }`; this
  handoff and staff-app's say a required `effectiveDate`, as members have. Built to the handoffs.
- **`rows` under `latest`.** This handoff asks both for `rows` built from the report entries and for `rows`
  byte-identical to before. They clash only with `latest` when a status entry is among the newest N: I kept
  `rows` (and `counts`) as they were, so during the expand `rows` can hold reports `entries` cut. Same
  content otherwise. When stage 5 drops `rows`, `counts` should be taken from the report entries kept.
- **Period closing helper.** `remove_guest_from_group` had no helper to reuse and `data/guests/services.py`
  can't import `data/small_groups/services.py` (that one imports it). `end_guest_period` lives in the
  guests module and both use it.
- **Row lock on add.** Beyond the handoff, `add_guest_to_group` locks an existing guest's row, so a
  deactivation can't run between its checks and the insert and leave an inactive guest in a group.
- **Status check before the group checks, `reactivate` permission before the service.** A `reactivate: true`
  without `guests: reactivate` is 403 even for an active guest or with `newGuest`, like the `guests: create`
  check.
- **Same-day re-add is 409.** Deactivating and reactivating-and-adding on the same day gets the existing
  "join date overlaps" 409 and rolls back, since the closed period ends today (guest periods already
  behave this way after a remove). Reactivating from Guest detail still works that day; adding works
  from the next day.
- **Sources stay in `data/small_groups/`** (`timeline_services.py`, `timeline_queries.py`), not a new
  `data/timeline/`: two sources don't justify a package yet.
- **Status filter name.** The list's `Literal` became `GuestStatusFilter`, since `GuestStatus` is now the enum.

## Stage 1: migration, models, seed

- `Guest` gains `status: Mapped[GuestStatus]` (`StrEnum`: `active`, `inactive`), VARCHAR(10) + CHECK,
  `server_default='active'`, NOT NULL, the same `Enum(...)` pattern as `Member.status`. Also
  `status_changed_at: Mapped[datetime | None]` (timestamptz).
- New model `GuestStatusChange` in `data/guests/models/` (import it in `data/models.py`), shaped like
  `MemberStatusChange`:
  - `guest_id` → `guests.id`, `status`, `reason`, `effective_date`, `note`, `changed_by_user_id`
    (plain string), `created_at`.
  - `reason` is a `GuestInactiveReason` StrEnum: `moved_away`, `stopped_attending`,
    `joined_another_church`, `deceased`, `other` (rule 3), VARCHAR(30) + CHECK.
  - Table CHECK `(status = 'inactive') = (reason IS NOT NULL)`.
  - Index `(guest_id, created_at DESC)`.
- `LeftReason` gains `GUEST_INACTIVE = "guest_inactive"`, written only by deactivating a guest
  (rule 5). Update its docstring. The remove body must **not** accept it, the same way it refuses
  `member_inactive`.
- Migration: the columns (every existing guest becomes `active`, no history backfilled), the table,
  and the `left_reason` CHECK extended. Downgrade drops them and fails loudly if any
  `left_reason = 'guest_inactive'` rows exist, as the member one does.
- Seed: two or three inactive guests, appended as a new seeder last in `SEEDERS` so every other
  seeded row stays identical:
  - one who left a guest group (period closed with `guest_inactive`);
  - one who was never in a group;
  - one who left, came back (reactivated and added to a guest group) and is active now, so the
    timeline has both kinds of status entry. Do the same for one member in
    `data/seed/inactive_members.py` only if no seeded member already has both.

## Stage 2: deactivate, reactivate, status on guests

**Services** in `data/guests/services.py`, mirroring the member ones:

- `deactivate_guest(session, guest, *, reason, effective_date, note, changed_by_user_id, today)`, in
  one transaction:
  1. Lock the guest row (`with_for_update`).
  2. `GuestAlreadyInactiveError` if already inactive.
  3. `effective_date > today` → 422.
  4. Close the open guest-group period, if any, with `left_at = today`,
     `left_reason = GUEST_INACTIVE` (rule 5). Reuse the closing helper `remove_guest_from_group`
     uses, so period-closing lives in one place. There's no leader check (guests can't lead).
  5. Insert the change row, set `status` and `status_changed_at`.
- `reactivate_guest(session, guest, *, note, changed_by_user_id, today)`: lock,
  `GuestAlreadyActiveError`, insert `(status=active, reason=None, effective_date=today)`, update the
  guest. Doesn't touch periods.

**Routes** (rate-limited like the member ones):

- `POST /guests/{guest_id}/deactivate`: `guests: deactivate`, guest in the caller's `GuestScope`
  (admins and elders have `all`). Body `GuestDeactivateSchema { reason, effectiveDate, note? }`
  (note trimmed, empty → `None`, max 1000). Returns the guest detail. 409 `already_inactive`.
- `POST /guests/{guest_id}/reactivate`: `guests: reactivate`, guest in scope. Body `{ note? }`.
  Returns the guest detail. 409 `already_active`. An inactive guest is in no group, so for leaders
  this is always 404; that's expected (rule 6). Leaders reactivate through stage 3.

**Fields** (rule 9 and *Contracts*):

- Guest detail gains `status`, `inactiveSince` (latest change's `effectiveDate` when inactive, else
  null), and `inactiveReason`, `inactiveNote`, `statusHistory` (newest first, `changedByName`
  resolved from `members.user_id` as for members) **only for `guests: deactivate`**, null
  otherwise. A separate history route isn't needed: guest detail is small.
- `GET /guests` rows and `GET /guests/search` results gain `status` and `inactiveSince`. List rows
  also gain `inactiveReason` (null without `guests: deactivate`) for the *Left* column.
- `GET /guests?status=`: now filters on `guests.status` (rule 10), not on being in a group. Keep
  `all` as the default the route has today; staff-app sends the tab. Tab counts follow the search but
  not the status, as today. Update the `GuestRow` docstring in `data/guests/results.py`.
- Search (`search_guests`, and the possible-match list behind *Add a new guest*) keeps returning
  inactive guests, with their status (rule 8).

**Out of the tag picker** (rule 8): `tag_search_query` in `data/members/queries.py` adds
`Guest.status == GuestStatus.ACTIVE` beside the member check. Saving a report that **newly** tags an
inactive guest is 422 `tag`, as for members: the people lookup in `data/small_groups/queries.py`
(around `inactive`) stops returning `false()` for guests, and the "guests never inactive" docstring
goes. Existing tags stay.

**Try:**

- admin and elder can deactivate and reactivate; leader, deacon and user get 403 on deactivate;
  leader gets 404 on reactivate (out of scope); user gets 403 on both.
- The guest's period closes today with `guest_inactive` while `effectiveDate` stays as sent.
- Repeating either call gives the matching 409; a future date, a long note, an unknown reason 422.
- `GET /guests?status=active` includes active guests who are in no group; `inactive` only inactive.
- An elder sees reason, note and history on detail; a leader viewing an active guest in scope sees
  `status` and nulls for the rest.
- The tag search never returns an inactive guest; tagging one newly is 422, keeping an old tag is fine.

## Stage 3: reactivate and add (rule 6)

- `SmallGroupGuestAddSchema` gains `reactivate: bool = False` and `reactivateNote: str | None`.
- `add_guest_to_group` (and `_check_guest_can_join`): an inactive `guestId` without `reactivate`
  raises `GuestInactiveError` → 409 `guest_inactive`. With `reactivate: true`:
  - needs `guests: reactivate` (403 otherwise), checked in the router like the `guests: create`
    check for a new guest;
  - reactivates (same service as stage 2, with the note and the caller's `sub`) and opens the new
    period in **one transaction**;
  - `joinedAt` (the report form's meeting date) still applies to the period; the status change's
    `effective_date` is today.
- `reactivate: true` on an active guest is ignored (no history row), so a stale page doesn't fail.
- `moveFromOtherGroup` stays as it is; an inactive guest is in no group, so the two don't meet.

**Try:** a guest-group leader adds an inactive guest without the flag (409 `guest_inactive`, nothing
changes), then with it (active, in the group, one history row with their `sub`); a leader of member
groups only can't search guests at all (guest rule 17), so they never get here; from the report form
with `joinedAt` earlier than today.

## Stage 4: timeline entries, expand (rules 12–15)

`GET /members/{id}/timeline` and `GET /guests/{id}/timeline` gain `entries` beside the existing
`rows`, which stay exactly as they are until stage 5.

**Sources.** Restructure `get_person_timeline` (`data/small_groups/timeline_services.py`) into one
source per kind and a shared step:

- A source takes the person, the caller's access (today `observation_groups`), and the resolved
  range or `latest`, and returns its entries already filtered for that caller. It filters by date in
  its query, not after loading everything (report tags' "a person's reports are few" won't hold once
  there are several sources). It also returns its own earliest date and groups, which `earliestDate`
  and `groups` need regardless of the range.
- **Report source:** today's logic, unchanged in what it shows.
- **Status source:** the person's `member_status_changes` or `guest_status_changes`, on
  `effective_date`. No group: it returns nothing when `smallGroupId` is set. Everyone who can open
  the timeline sees reason and note (rule 13); no extra check.
- **Shared step:** merge, sort newest first (ties on a date: status above report, then newest
  `created_at` / report id), apply `latest` across all kinds, take the minimum `earliestDate`, the
  union of `groups`. `counts` stays report-only.
- Keep the sources in `data/small_groups/` for now (or a new `data/timeline/` if that reads better);
  note the choice in the log.

**Schema** (`api/schemas/person_timeline.py`), a discriminated union on `kind`:

- `TimelineReportEntrySchema { kind: "report", date, report: TimelineRowSchema }`
- `TimelineStatusEntrySchema { kind: "status", date, status, reason, note, changedBy:
  { memberId, name } | null }`. `reason` is the member or guest enum by person type.
- `PersonTimelineSchema.entries: list[TimelineEntry]`. `rows` is built from the report entries, so
  the two never disagree.

**Try:** an elder and a leader in scope both see status entries with reason and note on a
reactivated member and guest; `latest=3` mixes kinds; a status entry outside the range is left out;
`smallGroupId` hides status entries; `earliestDate` is a status date when that's the oldest thing;
`rows` is byte-identical to before for every role (dump before and after).

## Stage 5: timeline entries, contract

Only after staff-app's timeline stage reading `entries` is deployed. Remove `rows` from
`PersonTimelineSchema` and the code that builds it. Note the staff-app commit in the log.

## Stage 6: docs

- `docs/ARCHITECTURE.md`: the two new routes in the role × route table, `reactivate` on the add-guest
  route, the new meaning of `GET /guests?status=`, and the timeline's entry kinds.
- A short note under the guests domain: what status means, that it's separate from being in a group,
  and that `guest_inactive` periods are written only by deactivation. Under the timeline: how to add
  a source.
- Tick the stages here. Mention in your final message anything staff-app must pick up (new fields,
  codes, `entries`).
