# Small groups API: changes for the staff app

Handoff spec for API changes the staff app's new small groups pages need. The pages are
designed in the Claude Design canvas "ekklesiaio Staff App"
(https://claude.ai/artifact/PLs9gdHVcigkRSAWJrsKs1, artboards `Groups*`, `GroupDetail*`,
`GroupForm*`). The existing endpoints (`api/routers/small_groups.py`, commit `c9f8ed7`) already
cover most of it; this spec adds what's missing and closes two gaps.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`small-groups-staff-app`** branch. Each stage must pass `uv run ruff check .` and
`uv run ty check`, and be tried against the local API (`fastapi dev`, `/docs`) before the next
one starts. There's no test runner yet, so note in *Decisions and deviations* what you tried and
how. If a stage needs a migration, follow the Alembic steps in `CLAUDE.md` (review the generated
file, check `downgrade -1` + `upgrade head` round-trips).

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, every mutating
route has its own `rate_limit(...)` scope, and service errors are domain exceptions the router maps
to HTTP codes.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Leader on the groups list | [x] | (this commit) |
| 2. Set the leader in one call | [x] | (this commit) |
| 3. Closed groups are read-only | [x] | (this commit) |
| 4. Docs | [x] | (this commit) |
| 5. Review fix: church-local "today" | [x] | (this commit) |

### Decisions and deviations

**Stage 1.** Joined an aliased active-leader `SmallGroupMember` and its `Member` onto the existing
active-member join and added the leader member's id to `GROUP BY` (the leader row is at most one per
group, so the count can't multiply; chosen over a subquery as the smaller change). Tried by running
`list_small_groups` against the seeded local DB: all 5 groups return their leader and
`active_member_count` (8/8/8/10/8). The seed has no closed group, so the `null` case for closed/leaderless
groups wasn't exercised, only follows from the outer joins.

**Stage 2.** Split out `_add_membership` and `_apply_role_change` (non-committing); `add_small_group_member`,
`change_small_group_member_role` and the new `set_small_group_leader` share them, with the same checks and
error order as before. Tried by calling the services in a rolled-back outer transaction against the seeded DB
(group 1, leader A, members B and D outside the group): `B` -> B leader and A co-leader with periods
closed/opened; `D` (not in group) -> added as leader, B co-leader; `D` again -> no change; `A` back -> D, who
joined today, corrected in place; unknown member and a closed group raise the 404/409 errors. The HTTP route
(`PUT /small-groups/{id}/leader`) was not called through `/docs`; its error mapping mirrors the member routes.
The existing POST/PATCH endpoints weren't re-run; their logic is moved unchanged.

**Stage 3.** `update_small_group` raises `SmallGroupClosedError` for a closed group and the PATCH route maps it
to 409 "This small group is closed.". Tried via the service in a rolled-back transaction: an active group
renames as before; after closing, the update raises and leaves the name unchanged. The HTTP route wasn't
called through `/docs`.

**Stage 5.** New `api/church_time.py` with `church_today()`; `_today()` and the close route both use it, so the
router has no other clock call. `ApiSettings.church_timezone` (`CHURCH_TIMEZONE`, default `America/Managua`) is
validated at startup (a bad name stops the API with a clear error; tried with `Nope/Zone`). Added `tzdata` as a
dependency (it was only pulled in for Windows, and the slim Docker image can't be assumed to ship zoneinfo data).
Tried by faking the clock to 01:11 UTC on Oct 15 (7:11 pm Oct 14 in Managua): `church_today()` returns Oct 14. Not
run through the HTTP routes. Per-service for now; once multi-tenancy lands the church/ministry carries its own
timezone. Existing rows untouched. The seed script still uses the UTC date (`data/seed/runner.py`): left as is,
it only places demo data relative to today.

**Stage 4.** One sentence added to the Members DB bullet in `CLAUDE.md`; nothing newly deferred, so `ROADMAP.md` is unchanged.

## What the staff app does with these endpoints

| Screen | Calls |
| --- | --- |
| Groups list (cards, Active/Closed/All tabs, search by group/leader/address) | `GET /small-groups` — **needs the leader (Stage 1)** |
| Group detail (members with roles, when & where) | `GET /small-groups/{id}` |
| New / edit group (name, meeting day, address) | `POST /small-groups`, `PATCH /small-groups/{id}` |
| Add member dialog (search members, pick role) | `GET /members` (client-side search), `POST /small-groups/{id}/members` |
| Row menu: change role | `PATCH /small-groups/{id}/members/{memberId}` |
| Make someone leader while there's already one | **new `PUT /small-groups/{id}/leader` (Stage 2)** |
| Row menu: remove from group | `DELETE /small-groups/{id}/members/{memberId}` |
| Close group | `POST /small-groups/{id}/close` |

## Stage 1: Leader on the groups list

The list cards show each group's leader ("Leader: Andrea Gutiérrez", or "No leader yet"), and the
list search matches the leader's name. `GET /small-groups` doesn't return it, and one detail call
per card is wasteful.

**Files:** `data/small_groups/queries.py`, `data/small_groups/results.py`,
`api/schemas/small_groups.py`, `api/routers/small_groups.py`.

1. `list_small_groups_query()`: outer-join the group's **active leader** row (an aliased
   `SmallGroupMember` with `role == LEADER` and `left_at IS NULL`) and its `Member`, and select
   `leader_member_id` and `leader_name`. The partial unique index guarantees at most one such row
   per group, so the join can't multiply rows; still keep the active-member count correct
   (add the leader columns to `group_by`, or count in a subquery, whichever reads better — note it).
2. `SmallGroupSummary` and `SmallGroupSummarySchema` gain `leader_member_id: int | None` and
   `leader_name: str | None` (camelCase on the wire: `leaderMemberId`, `leaderName`).
3. Closed groups naturally return `null` (their memberships ended on close).

**Done when:** `GET /small-groups` returns the leader for groups that have one and `null` for
those without one and for closed groups; `activeMemberCount` is unchanged for every group.

## Stage 2: Set the leader in one call

The design lets staff make someone the leader when the group already has one, after a confirm
dialog: "Andrea Gutiérrez leads this group now. She'll become a co-leader and Carlos will lead
from today." Today that takes two calls (demote, then promote); if the second fails, the group is
left without a leader. Do it in one transaction instead.

**New endpoint:** `PUT /small-groups/{small_group_id}/leader`, body `{ "memberId": int }`,
returns `SmallGroupDetailSchema`. Rate limit `rate_limit("30/minute", scope="set_small_group_leader")`.

Behavior (all in **one commit**):

1. Group closed → 409 "This small group is closed." Member doesn't exist → 404 (same message as
   adding a member).
2. The member is already the active leader → no change, 200 with the detail.
3. If there's a current leader (someone else), change their role to `co_leader`, keeping history
   exactly like `change_small_group_member_role` does (close the period and open a new one, or
   correct it in place if it started today).
4. Then make the target the leader: if they're an active member, change their role the same way;
   if they're not in the group, add them as `leader` joining today.
5. Order matters: demote, then `session.flush()`, then promote, or the partial unique index on the
   active leader sees two leaders. A lost race still maps through `_commit_or_raise_conflict`
   (409 "This small group already has a leader.").

**Refactor to make this clean:** split `change_small_group_member_role` and
`add_small_group_member` into non-committing helpers (e.g. `_apply_role_change(...)`,
`_add_membership(...)`) that the existing public functions and the new `set_small_group_leader(...)`
service all use, so the history rules live in one place. Behavior of the existing endpoints must not
change.

The staff app will call this endpoint from: the row menu's "Leader" option when a leader exists,
and the add-member dialog when "Leader" is picked and a leader exists (it adds the member with
`PUT .../leader` instead of `POST .../members`). Without a current leader it can keep using the
existing calls; this endpoint works in both cases.

**Done when:** in a group with leader A and members B, C:
- `PUT .../leader {B}` → B leader, A co-leader, history rows for both closed/opened correctly
  (or corrected in place if they joined today);
- `PUT .../leader {D}` (D not in the group) → D added as leader joining today, B co-leader;
- `PUT .../leader {D}` again → 200, no change;
- on a closed group → 409; unknown member → 404;
- `POST .../members` and `PATCH .../members/{id}` behave exactly as before.

## Stage 3: Closed groups are read-only

`update_small_group` doesn't check `closed_at`, so `PATCH /small-groups/{id}` can rename or
re-schedule a closed group. The design treats closed groups as read-only (no Edit button), so the
API should agree.

- `update_small_group` raises `SmallGroupClosedError` when `closed_at` is set; the route maps it to
  409 "This small group is closed." (same as the member routes).
- `DELETE .../members/{id}` on a closed group already returns 404 (no active memberships left);
  leave it.

**Done when:** `PATCH` on a closed group returns 409 and changes nothing; on an active group it
works as before.

## Stage 4: Docs

- `CLAUDE.md` → *Architecture*: mention the leader columns on the list and the single-transaction
  leader change, in a line or two (keep that file short).
- `docs/ROADMAP.md`: nothing unless something new is deferred.
- Mark the stages above done with their commits and finish *Decisions and deviations*.

## Review follow-ups (browser review, 2026-10-14)

Reviewed through the staff app against the local API. The list's leader columns, the
single-transaction leader change (`PUT .../leader`, both "add as leader" and "promote an existing
member") and the closed-group `PATCH` 409 all behave as specified. One bug goes in **Stage 5**.

## Stage 5: Review fix — church-local "today"

**Bug:** every "today" in `api/routers/small_groups.py` is `datetime.now(tz=UTC).date()` (`_today()`
and the inline call in `post_close_small_group`). The church is in Managua (UTC-6), so from 6 pm
local time on, "today" is already tomorrow: a member added at 7:11 pm on Oct 14 got
`joined_at = 2026-10-15`, and a group closed that evening got `closed_at = 2026-10-15`. It affects
add, role change, leader change, remove and close.

**Fix:**

1. Add a timezone setting (e.g. `church_timezone: str = "America/Managua"`, env `CHURCH_TIMEZONE`)
   to `ApiSettings`, validated at startup with `zoneinfo.ZoneInfo` (fail fast on a bad name;
   `tzdata` may be needed in the Docker image, check). Document it in `.env.example`.
2. One helper, e.g. `church_today() -> date` (`datetime.now(ZoneInfo(settings.church_timezone)).date()`),
   used by `_today()` **and** the close route, so there's a single source of "today".
3. Keep it per-service for now (one church per deployment today). Note under *Decisions* that this
   becomes per-church once multi-tenancy lands (the church/ministry would carry its own timezone).
4. Don't rewrite existing rows; dates already stored a day ahead in local/dev data can stay.

**Done when:** with the API running after 6 pm Managua time (or with the clock/zone faked in a
quick script), adding a member, changing a role, setting the leader, removing a member and closing
a group all store the **Managua** date; `ruff` and `ty` pass; `.env.example` and `CLAUDE.md`
(*Architecture*, one line) mention the setting.

## Not in this spec (open questions for Luis)

- **Meeting time.** The API only stores a meeting day; the design shows "Thursdays" with no time.
  Adding `meeting_time` (nullable `TIME`) would need a migration plus schema fields; do it only
  if asked.
- **A member's current groups on `GET /members`.** The add-member dialog could hint "Also in
  Hombres de Valor" for each search result, but the members list doesn't carry group info. The
  staff app will show only "Already in this group" (known from the group detail) unless this is
  added later.
- **Reopening a closed group.** Not supported and not designed.

## Add member with `joinedAt`

`POST /small-groups/{id}/members` takes an optional `joinedAt` (date, default `church_today()`) so staff can
backfill migrated data. Reports only count a member from `joinedAt` on. A future date is 422; a date inside
one of the member's earlier closed periods in the same group is 409.
