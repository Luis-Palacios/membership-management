# Small group leader access: role checks and scoped small group routes

Handoff spec for the membership-management side of **small group leader access**. Read the
cross-repo spec first: `../docs/specs/small-group-leader-access.md` (workspace folder
`members-management/docs/specs/`); it holds the rules (numbered below as *rule N*). In short:
`admin`/`elder` keep full access; `smallGroupLeader`/`deacon` see and work on only the groups
their linked member leads or co-leads; every other role gets 403 on the small group routes.

This is the first role gating beyond the member-link endpoints. It builds on what member linking
added: `require_roles` (`api/jwt_auth.py`), `get_current_member` / `CurrentMemberDep`
(`api/current_member.py`) and `member_active_leads_query` (`data/members/queries.py`).
**No migration is expected**; confirm with `uv run alembic check`.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`small-group-leader-access`** branch (the same name in every repo). Each stage must pass
`uv run ruff check .` and `uv run ty check`, and be tried against the local API (`fastapi dev`,
`/docs`, or `TestClient` with the claims dependency overridden, as the linking stages did) before
the next one starts. There's no test runner yet, so note in *Decisions and deviations* what you
tried and how.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, every mutating
route has its own `rate_limit(...)` scope, and service errors are domain exceptions the router maps
to HTTP codes.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Role sets and the small group scope | [x] | 6bf035f |
| 2. Scoped reads; full-role-only routes | [x] | a7c344e |
| 3. Scoped writes and the leadership limits | [x] | see git log |
| 4. Docs | [ ] | |

### Decisions and deviations

- Verification: no test runner, so each stage was tried with a scratch script (kept outside the repo)
  that seeds `ZZ`-prefixed members and groups in the local members DB, calls the API through
  `TestClient` with `get_current_claims` overridden, and deletes the rows afterwards.
- Stage 1: the scope predicate lives in `data/small_groups/queries.py` (`leads_in_scope_condition`)
  and is shared by `led_small_group_ids_query` and `member_active_leads_query`, so `/me` `leads` and
  the access scope can't drift. Tried: leader, co-leader (open and closed group), member only, former
  leader, leader at close, removed before close, no member (`[]`); `admin`/`elder` full, `deacon`
  scoped, `user`/`pending` 403. `alembic check`: no migration needed.
- Stage 2: `_get_or_404` takes an optional scope (full-only routes don't need one). The three member
  routes also got `SmallGroupScopeDep` here, so they are never open to `user`/`pending` between
  stages; the rule 9 limits come in stage 3. Tried through the real app: scoped users list only their
  groups (a leader at close sees the closed group, a former leader and an unlinked user see `[]`);
  out-of-scope and unknown ids give the same 404; `user`/`pending` 403 on every route; `deacon` 403 on
  create/close/set leader; `admin` unchanged.
- Stage 3: the rule 9 checks are `ensure_scoped_caller_can_add_member` and
  `ensure_scoped_caller_can_change_member` in `api/access.py` (authorization stays out of the
  services). `_active_membership` is now public as `get_active_membership`. Tried as `smallGroupLeader`
  (leader), `deacon` (co-leader), `user` and `admin` on every row of the stage table plus the allowed
  moves (add `member`/`co_leader`, `member` <-> `co_leader`, remove a member or another co-leader),
  unknown member, non-member target, out-of-scope group (404) and a closed group (409 on add). A
  co-leader acting on the leader's row gets the leadership message; on their own row, the own-row
  message. Scratch rows were deleted afterwards.
- Closed groups: changing a role or adding returns 409 as before. Removing a member there returns 404
  "not in the small group" (all periods ended at close), also as before; not changed here.

## Who can do what

| Route | `admin`, `elder` | `smallGroupLeader`, `deacon` | any other role |
| --- | --- | --- | --- |
| `GET /small-groups` | all groups | only groups in scope (may be `[]`) | 403 |
| `GET /small-groups/{id}` | yes | in scope, else 404 | 403 |
| `PATCH /small-groups/{id}` | yes | in scope, else 404 | 403 |
| `POST /small-groups/{id}/members` | yes | in scope, else 404; rule 9 limits | 403 |
| `PATCH /small-groups/{id}/members/{memberId}` | yes | in scope, else 404; rule 9 limits | 403 |
| `DELETE /small-groups/{id}/members/{memberId}` | yes | in scope, else 404; rule 9 limits | 403 |
| `POST /small-groups` | yes | 403 | 403 |
| `POST /small-groups/{id}/close` | yes | 403 | 403 |
| `PUT /small-groups/{id}/leader` | yes | 403 | 403 |

Not touched here: `/members`, `/people`, `/applications`, `/me` routes keep their current access
(rule 7). Leaders need `GET /members` for the add-member picker.

**Scope** (rules 2, 3, 11): the groups where the caller's linked member has a `leader` or
`co_leader` period that is either

- **active**: `left_at IS NULL`, or
- **ended by the group closing**: the group has `closed_at` and the period's `left_at >= closed_at`.
  `close_small_group` ends every active period on the close date (`greatest(joined_at,
  closed_at)`), and closed groups accept no edits, so these are exactly the people who led it when
  it closed. They see it read-only (rule 11). Edge case, accepted: someone removed as leader on
  the same day the group was closed also matches.

Anyone else, including a former leader whose period ended before the group closed, has no scope
for that group (rule 3). A scoped role with no linked member, or whose member leads nothing, has
an empty scope: `GET /small-groups` returns `[]` and every single-group route returns 404 (rule 4).

## Stage 1: Role sets and the small group scope

**Files:** new `api/access.py`, `data/small_groups/queries.py`, `data/small_groups/services.py`,
`data/members/queries.py` (or services), `api/routers/me.py` if it builds `leads` itself.

- In `api/access.py`, the third hand mirror of auth-server's roles (rule 8; keep a comment pointing
  at `auth-server/src/permissions/statements.ts` and `staff-app/lib/auth/roles.ts`):
  - `FULL_ACCESS_ROLES = frozenset({"admin", "elder"})`
  - `SCOPED_ROLES = frozenset({"smallGroupLeader", "deacon"})`
- Query `led_small_group_ids_query(member_id)` in `data/small_groups/queries.py`: distinct
  `small_group_id`s for the scope rule above (join `SmallGroup` for `closed_at`). Service wrapper
  `get_led_small_group_ids(session, member_id) -> frozenset[int]`.
- `SmallGroupScope` (frozen dataclass in `api/access.py`): `full: bool`,
  `group_ids: frozenset[int]`, `member_id: int | None`, with `includes(group_id) -> bool`.
- Dependency `get_small_group_scope(claims, member) -> SmallGroupScope` and
  `SmallGroupScopeDep`:
  - role in `FULL_ACCESS_ROLES` → `full=True`, no query (`member_id` still set if linked).
  - role in `SCOPED_ROLES` → `full=False`, `group_ids` from the query, or empty with no member.
  - anything else → 403 `"You don't have permission to do this."` (same text as `require_roles`).
- **`GET /me` uses the same rule.** Change `member_active_leads_query` (or replace it) so `leads`
  is exactly the scope above, with the period's role. Today it has the active-only half, so a
  leader of a closed group would see the group in `/small-groups` but not in `leads`. Keep the
  name order. Its comment says "closed groups included"; after this stage that is true.
- No route uses the scope yet. Try the query and the dependency with `TestClient` on a scratch app
  or directly against the local DB: leader, co-leader, member only, former leader, leader at close,
  removed before close, no member; and `admin`, `deacon`, `user`.

## Stage 2: Scoped reads; full-role-only routes

**Files:** `api/routers/small_groups.py`, `data/small_groups/queries.py`, `data/small_groups/services.py`.

- The router keeps `get_current_claims` at router level; add `SmallGroupScopeDep` to every route
  that the table above opens to scoped roles. Routes for full roles only get
  `Depends(require_roles("admin", "elder"))` instead (`POST ""`, `POST /{id}/close`,
  `PUT /{id}/leader`).
- `list_small_groups` takes an optional `only_ids: frozenset[int] | None`; the query adds
  `SmallGroup.id.in_(only_ids)` when it is given (an empty set returns no rows without a query
  if that's simpler). Filter in SQL, not in Python after loading (spec, *Contracts*).
- `_get_or_404(db, small_group_id, scope)`: 404 with the existing message when the group doesn't
  exist **or** `not scope.includes(id)`. Same message for both, so ids outside the scope don't leak
  (rule 4).
- Try: each role on list and detail; scoped user gets only their groups; out-of-scope id and
  unknown id give the same 404; `user` gets 403; `deacon` gets 403 on create, close and set
  leader; `admin` unchanged everywhere.

## Stage 3: Scoped writes and the leadership limits

**Files:** `api/routers/small_groups.py`, `data/small_groups/services.py`.

`PATCH /small-groups/{id}` only needs the scoped `_get_or_404` (the closed-group 409 stays as is).

For the three member routes, after the scoped `_get_or_404`, a scoped (`not scope.full`) caller
is also checked against rule 9. Full roles skip this.

| Route | Refused for a scoped caller when | Response |
| --- | --- | --- |
| `POST .../members` | `role == "leader"` | 403 `Only admins and elders can change who leads a group.` |
| `PATCH .../members/{memberId}` | `memberId == scope.member_id` | 403 `Ask an admin or elder to change your own role in this group.` |
| | new `role == "leader"`, or the target's current role is `leader` | 403 `Only admins and elders can change who leads a group.` |
| `DELETE .../members/{memberId}` | `memberId == scope.member_id` | 403 `Ask an admin or elder to change your own role in this group.` |
| | the target's current role is `leader` | 403 `Only admins and elders can change who leads a group.` |

- The target's current role needs a public lookup; expose the existing `_active_membership` as
  `get_active_membership(session, small_group_id, member_id)` (or return just the role). If the
  target has no active membership, let the service raise as today (404 "This member is not in the
  small group.").
- Check order: scope (404) → own row → leadership → service. The checks are authorization, so
  they live in the router (or a small helper in `api/access.py`), not in the services, which stay
  role-agnostic and keep serving full roles unchanged.
- Closed groups: unchanged. Every write still 409s for everyone, and a leader at close passes the
  scope check, so they get the same 409 an admin does.
- Try every row of the table above as a leader and as a co-leader, plus the allowed moves
  (`member` ↔ `co_leader`, add `member`/`co_leader`, remove a member or another co-leader), and
  that `admin` can still do all of it. Then clean up the scratch data.

## Stage 4: Docs

- `CLAUDE.md`: one sentence in the Members DB bullet: small group routes are role-gated through
  `api/access.py` (full roles, scoped roles limited to led groups, everything else 403); point at
  the cross-repo spec.
- `ROADMAP.md`: tick or update the Phase 9 step (role gating) to say the small group routes are
  done and members, people and applications are still open.
- `docs/ARCHITECTURE.md`: if it describes auth, add the scope dependency next to `require_roles`.

## Not in this spec

- Small group **report** endpoints. They come with `docs/specs/small-group-reports.md` (next), which
  reuses `SmallGroupScopeDep` and the cross-repo rules 10 and 11.
- Role checks on members, people and applications routes.
- Former leaders seeing past groups or reports.
- Caching the scope across requests (one indexed query per request is fine).
