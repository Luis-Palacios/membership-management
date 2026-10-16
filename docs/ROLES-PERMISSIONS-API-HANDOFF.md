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
| 1. Claims and guard | [ ] | |
| 2. Replace role checks | [ ] | |
| 3. Gate the open routers | [ ] | |
| 4. Members scope and picker | [ ] | |
| 5. Docs | [ ] | |

### Decisions and deviations

(Filled in per stage.)

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
