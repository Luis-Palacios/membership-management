# Roles and permissions: membership-management changes

Handoff spec for the membership-management side of **roles and permissions**. Read the cross-repo
spec first: `../docs/specs/roles-and-permissions.md` (workspace folder
`members-management/docs/specs/`). It holds the rules (numbered below as *rule N*); this file is
only what changes in this API.

**What this repo does:** stops checking role names. Every route checks a **permission** read from
the JWT's `perms` claim, which auth-server computes from `statements.ts` (`permissionsFor`). The
hand-mirrored role sets in `api/access.py` and `require_roles` go away. The members routes, the
applications routes and the people routes, which accept any valid JWT today, get gated. Leaders get
scoped member detail and edit, plus a names-only picker (`GET /members/options`).

Work through it **stage by stage**, one reviewable commit per stage, on the **`roles-permissions`**
branch. Each stage must pass `uv run ruff check .` and `uv run ty check`. There's no test runner,
so note in *Decisions and deviations* what was tried and how. **Needs auth-server stage 2 running
locally** (`perms` in `GET /api/auth/token`); tokens are real ones minted by it for every role
(`admin`, `elder`, `smallGroupLeader`, `deacon`, `user`, `pending`), never hand-made.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
schemas are `CamelModel`, every mutating route keeps its own `rate_limit(...)` scope, service errors
are domain exceptions the router maps to HTTP codes.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Claims and guard | [x] | (this commit) |
| 2. Replace role checks | [x] | (this commit) |
| 3. Gate the open routers | [x] | (this commit) |
| 4. Members scope and picker | [x] | (this commit) |
| 5. Docs | [ ] | |

### Decisions and deviations

- Tokens for every check are real: one scratch user + session per role inserted in auth-server's
  dev DB (`rp-test-<role>`, no email sent), the session cookie signed with `BETTER_AUTH_SECRET`,
  and `GET :5000/api/auth/token` called with it. The scratch users are deleted after stage 5.
- Stage 1: `perms` defaults to `{}`; `has_permission` is a plain lookup, `require_permission` is
  all-of. Tried on a scratch FastAPI app with the real `get_current_claims` (JWKS from `:5000`):
  `members: view+all`, `members: search`, `smallGroups: view`, `smallGroups: setLeader`,
  `smallGroupReports: viewObservations`, `user: list` give 200 for admin and elder on all six;
  smallGroupLeader and deacon 200 only on `search` and `smallGroups: view`; user and pending 403
  on all. No token / garbage token 401. A payload without `perms` validates to `{}`; a list instead
  of a dict fails validation (so 401). `ruff` and `ty` pass.
- Stage 2: `get_small_group_scope` 403s without `smallGroups: view`, `full` is `smallGroups: all`.
  Rule 9 helpers renamed `ensure_caller_can_add_member` / `ensure_caller_can_change_member` and
  take the claims: the own-row check still keys on `scope.full` (`all`), the leader checks on
  `setLeader`, so admin/elder behave as before. **Close and set-leader now also go through the
  scope** (they skipped it because only full roles reached them): rule 3 says an action without
  `all` is scoped, so a future role with `close` but not `all` stays inside its groups.
  `_get_or_404` therefore always takes a scope. The report roster (`GET
  /small-groups/{id}/report-roster`) is read-only, so it needs `smallGroupReports: view`, not
  `create`. `caller_is_scoped` on report create (the submitter must have led on that date) stays
  `not scope.full`: it's about records, not an action. Observations: `sees_all_observations` is
  `smallGroupReports: viewObservations`; the submitter still sees their own. `require_roles`
  deleted; `members: link` on the two link routes. Tried with the role runner (real app, real
  tokens, one rolled-back members-DB transaction per role, leader linked to member 6, deacon to
  41): admin and elder unchanged on every small group, report and link route; leader sees groups
  1 and closed 6, deacon only 2, others 404; leader can update, add, change and remove in group 1,
  gets 403 on adding a leader, changing their own row, promoting to leader, set-leader, close and
  create; deacon 404 in group 1; week 403 for both; report observations visible to the leader on
  their own report 8 and not on 37, to the deacon not on 14; user and pending 403 everywhere; link
  routes 403 for everyone but admin/elder. Dev data checked unchanged afterwards. `ruff` and `ty`
  pass.
- Stage 3: permissions as in the table above; people take `membershipApplications: view` on the
  router (both its routes need it), applications per route. Member detail and update need `all` for
  now so the branch never exposes other members to leaders between stages; stage 4 swaps that for
  the members scope. Tried with the role runner: `GET /members`, member detail, create, update
  (phone and email) 200/201 for admin and elder and 403 for the other four; approve / reject
  200 for admin and elder (still placeholders) and 403 for the rest; `GET /me` 200 for all six
  (`pending` too), with `member` 6 / 41 for the linked leader and deacon. **The assimilation DB
  isn't reachable from this machine** (ODBC Driver 18: `OpenSSL library could not be loaded`), so
  the applications and people reads were only checked as far as the gate: 403 for leader,
  deacon, user and pending, and past the gate (500 from the DB connection) for admin and elder.
  `ruff` and `ty` pass.
- Stage 4: `MemberScope` / `get_member_scope` in `api/access.py`, next to the small group scope it
  builds on (`_small_group_scope`, shared with `get_small_group_scope`, returns None instead of
  403 so a caller with `members: view` but no `smallGroups: view` just gets an empty scope).
  `group_ids=None` means "any open group" (a caller with `smallGroups: all` but not `members:
  all`; no role has that today). The check is one `LIMIT 1` query
  (`member_active_in_open_groups_query`), run only for a single record; there's no scoped list
  (out of this spec). Detail and update dropped the stage 3 `all`. The email rule is literal: a
  body with `email` is 403 without `members: all` **even when the value is unchanged**, so
  staff-app's leader form must leave the key out, not send it back. `GET /members/{id}` still
  returns `email` to leaders (rule 8 only stops them changing it). `GET /members/options` is
  ordered by name then id. Tried with the role runner (groups section first, so member 14 has been
  removed from group 1, and member 13 given a membership in closed group 6, both inside the
  rolled-back transaction): options 200 with 58 `{id, name}` for admin, elder, leader and deacon,
  403 for user and pending; leader 200 on members 6 (self), 7, 8, 30 (group 1 and closed group 6)
  and 9 (added to group 1 earlier in the run), 404 on 14 (former), 13 (only in the closed group),
  23 and 41 (group 2); deacon the mirror image (23, 41 yes; group 1 members no); leader and
  deacon phone updates 200 in scope and 404 out of it; email updates 403 in scope (also with the
  value unchanged), 404 out of scope; admin and elder 200 on all of it; `GET /members` still 403
  for leader and deacon. `ruff` and `ty` pass.

## The JWT this API receives (auth-server stage 2)

Payload `{ sub, role, perms, iat, exp, iss, aud }`. `perms` is `Record<resource, action[]>`, the
role's statements as declared:

| Role | `perms` |
| --- | --- |
| `admin` | every app resource, all actions, plus better-auth's `user` and `session` keys |
| `elder` | every app resource, all actions, plus `user: create, list, get, ban, set-role` |
| `smallGroupLeader`, `deacon` | `members: view, search, update` · `smallGroups: view, update, manageMembers` · `smallGroupReports: view, create, update, delete` |
| `user`, `pending` | `{}` |

This API reads only the app resources (`members`, `membershipApplications`, `smallGroups`,
`smallGroupReports`) and ignores the rest. **Fail closed (rule 10):** a token without `perms`
(minted before auth-server stage 2) has no permissions; it is still a valid token, so it gets 403,
not 401. `role` stays in the claims for `GET /me` (display only); nothing checks it.

## Stage 1: Claims and guard

**File:** `api/jwt_auth.py`.

- `AuthClaims.perms: dict[str, list[str]] = {}`. A malformed `perms` (not that shape) fails
  validation and is a 401 like any other bad token.
- `has_permission(claims, resource, action) -> bool`.
- `require_permission(resource, *actions)`: a dependency factory like `require_roles`, next to it.
  All of `actions` must be present (all-of, the same as staff-app's `can`); otherwise 403 `You
  don't have permission to do this.`. Not applied to any route yet.

## Stage 2: Replace role checks

**Files:** `api/access.py`, `api/jwt_auth.py`, `api/routers/small_groups.py`,
`api/routers/small_group_reports.py`, `api/routers/members.py` (link routes).

Rule 6 table, applied:

- `get_small_group_scope`: 403 without `smallGroups: view`. With `smallGroups: all` the scope is
  `full`; otherwise it is the groups the caller's member leads or co-led when closed (unchanged).
  Leading a group grants nothing by itself (rule 4): no `view`, no scope. `FULL_ACCESS_ROLES` /
  `SCOPED_ROLES` deleted.
- Small group routes name their permission: create `smallGroups: create`, update `update`, close
  `close`, set leader `setLeader`, add / change role / remove members `manageMembers` (+ scope).
  List and detail need only the scope dependency (`view`).
- Leader-access rule 9, rewritten: assigning, changing to or removing a `leader` needs
  `smallGroups: setLeader`; without `smallGroups: all` you can't change your own row.
- Reports: list, summary, detail and the report roster `smallGroupReports: view`; create / update
  / delete their own action; all of them keep the `smallGroups` scope. Week view
  `smallGroups: all` + `smallGroupReports: viewObservations`. `sees_all_observations` comes from
  `smallGroupReports: viewObservations` (the submitter still sees their own).
- Member link routes (`PUT/DELETE /members/{id}/user`): `members: link`.
- Then delete `require_roles`.

## Stage 3: Gate the open routers

Rule 6, last row. Every route now names its permission:

| Route | Permission |
| --- | --- |
| `GET /members` | `members: view` + `all` (rule 8: full rows, emails and phones) |
| `GET /members/{id}` | `members: view` + `all` until stage 4 scopes it |
| `POST /members` | `members: create` |
| `PATCH /members/{id}` | `members: update` + `all` until stage 4 scopes it |
| `GET /applications/recents`, `/recents/count`, `/{id}` | `membershipApplications: view` |
| `POST /applications/approve` / `reject` | `membershipApplications: approve` / `reject` |
| `GET /people/{id}/events`, `/first-assistance` | `membershipApplications: view` |

Not gated by a permission, on purpose: `GET /me` (every signed-in user, `pending` too; it's how
staff-app learns who the caller is), `GET /health`, `/internal/*` (shared token, not a JWT).

## Stage 4: Members scope and picker

- **`get_member_scope`** (rule 3): `members: all` → every member. Otherwise members with an
  **active** membership (`left_at IS NULL`) in an **open** group in the caller's `smallGroups`
  scope (no `smallGroups: view` → empty). Members of a closed group they led, and former members,
  are out of scope.
- `GET /members/{id}`: `members: view` + scope; out of scope is 404 with the not-found message.
- `PATCH /members/{id}`: `members: update` + scope. A body with `email` from a caller without
  `members: all` is 403 (rule 8; email is what the invite → member link matches on), checked after
  the scope so out-of-scope stays 404.
- **`GET /members/options`** → `[{ id, name }]`, every member, ordered by name, with
  `members: search`. For the add-member picker, admins included.

## Stage 5: Docs

This log; `ARCHITECTURE.md` permissions section with a role × route table; `CLAUDE.md` lines about
`access.py` / `require_roles`; every role tried against every route.

## Other repos (not done here)

- staff-app: the add-member picker moves to `GET /members/options`; leaders get member detail and
  edit with no email field; regenerate API types (new route, `/members/{id}` now 403/404 for some
  roles).
- Workspace `CLAUDE.md`: drop "mirrored by hand … in membership-management's role sets" once
  staff-app is done.
