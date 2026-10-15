# Member ↔ user link: changes for the staff app

Handoff spec for the membership-management side of **member ↔ user linking**. Read the cross-repo
spec first: `../docs/specs/member-user-linking.md` (workspace folder
`members-management/docs/specs/`); it holds the rules and the contract. The screens are designed in
the Claude Design canvas "ekklesiaio Staff App"
(https://claude.ai/artifact/PLs9gdHVcigkRSAWJrsKs1, page "Member ↔ User linking").

`members.user_id` (String(255), nullable, unique `uq_members_user_id`) already exists, so **no
migration is expected**; confirm with `uv run alembic check`. Nothing reads or writes the column
yet.

Work through it **stage by stage**, one reviewable commit per stage, on the
**`member-user-linking`** branch (the same name in every repo). Each stage must pass `uv run ruff check .` and `uv run ty check`,
and be tried against the local API (`fastapi dev`, `/docs`) before the next one starts. There's no
test runner yet, so note in *Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, every mutating
route has its own `rate_limit(...)` scope, and service errors are domain exceptions the router maps
to HTTP codes.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. `userId` on member responses | [x] | (this commit) |
| 2. Role check for admin/elder | [x] | (this commit) |
| 3. Link and unlink a user | [x] | (this commit) |
| 4. Internal accept-invite endpoint | [x] | (this commit) |
| 5. Current member and `GET /me` | [ ] | |
| 6. Docs | [ ] | |

### Decisions and deviations

- Stage 1: `user_id` added to the `list_members` query, `MemberSummary` result and both schemas. Create/update schemas untouched (confirmed `userId` is absent from them in OpenAPI). Tried with `TestClient` against the local Postgres with the claims dependency overridden: `GET /members` and `GET /members/1` return `userId: null`. `ruff` and `ty` pass.
- Stage 2: `require_roles(*allowed)` in `api/jwt_auth.py`, built on `CurrentClaimsDep`; exact match on `claims.role` (auth-server roles are single values, no comma lists). Not applied to any route yet (stage 3 does). Tried on a scratch FastAPI app with the claims dependency overridden: `admin` and `elder` get 200; `smallGroupLeader` and an empty role get 403 `You don't have permission to do this.`. `ruff` and `ty` pass.
- Stage 3: `link_member_user` / `unlink_member_user` in `data/members/services.py` with `MemberAlreadyLinkedError` and `UserAlreadyLinkedError`; the check-first query plus a catch of `uq_members_user_id` on flush both map to the same 409. `PUT` body schema is `MemberUserLinkSchema` (`UserId`: strip, 1 to 255). Tried with `TestClient` against the local Postgres, claims overridden, then unlinked everything (0 links before and after): link 200, same user again 200, other user on the same member 409, user already on another member 409, blank `userId` 422, missing member 404 on both verbs, `elder` allowed, `smallGroupLeader` 403 on both verbs, unlink 204 twice. The race branch (unique violation on flush) was not exercised, only written to mirror `_flush_or_raise_duplicate`. `ruff` and `ty` pass.
- Stage 4: `internal_api_token: SecretStr | None` in `ApiSettings`, plus an `environment` field (same required `ENVIRONMENT` alias the DB settings use) so a validator can demand the token outside `local`. An empty token counts as unset, so an empty `X-Internal-Token` header can never match. Router `api/routers/internal.py` (`include_in_schema=False`, no JWT dependency), logic in `link_member_by_accepted_invite` (`data/members/services.py`): user already linked, zero or several email matches (`limit(2)`; `members.email` is unique but case-sensitive, so `A@x.com` and `a@x.com` can coexist) all return `linked: false`; a unique violation on commit is rolled back to the same result. Tried with `TestClient` against the local Postgres (three scratch members, deleted afterwards): mixed-case email links (200, `linked: true`); same user again, member already linked, two case-variant duplicates and no match all 200 `linked: false` with nothing changed; wrong or missing token 401; blank `userId` 422; route absent from OpenAPI; token unset locally 404; `ENVIRONMENT=staging` without the token fails at startup. `ruff`, `ty` and `alembic check` pass. Not tried against a real auth-server invite acceptance yet. `.env.example` line for `INTERNAL_API_TOKEN` added here rather than in stage 6.

## What the staff app does with these endpoints

| Screen | Calls |
| --- | --- |
| Members list: Account column and Linked / Invited / No account filter | `GET /members` (now with `userId`); invites come from auth-server |
| Member detail: Account card and header pill | `GET /members/{id}` (now with `userId`) |
| Link existing user dialog | `PUT /members/{id}/user` |
| Unlink dialog (member or user side) | `DELETE /members/{id}/user` |
| Users list "Member" column; User detail "Linked member" | `GET /members` (find the member whose `userId` is the user) |
| Invite accepted | auth-server → `POST /internal/member-links/accepted-invite` |
| Every page: who the signed-in user is as a member, which groups they lead | `GET /me` |

## Stage 1: `userId` on member responses

`MemberSummarySchema` and `MemberDetailSchema` get `user_id: str | None` (camelCase `userId`
over the wire). Add it to `list_members` / `_detail`. Never accept `user_id` from
`MemberCreateSchema` / `MemberUpdateSchema`; linking only goes through the endpoints below.

**Files:** `api/schemas/members.py`, `api/routers/members.py`, and the service/query that builds
the list if it selects columns explicitly.

## Stage 2: Role check

The JWT already carries `role` (`AuthClaims.role`, deliberately a plain `str` until authorization
lands). Add a small dependency, e.g. `require_roles("admin", "elder")` in `api/jwt_auth.py`, that
returns the claims or raises `HTTPException(403, "You don't have permission to do this.")`. Keep
it generic (takes role names), so the future role-based gating can reuse it, but **apply it only to
the endpoints in this spec**; don't retrofit existing routes here.

The role names are the auth-server role keys: `admin`, `elder`.

## Stage 3: Link and unlink

**Files:** `data/members/services.py`, `api/routers/members.py`, `api/schemas/members.py`.

`PUT /members/{member_id}/user`, body `{ "userId": str }` (`StringConstraints`: strip, min 1, max
255). Rate limit `rate_limit("20/minute", scope="link_member_user")`, plus `require_roles`.

- 404 `Member with ID {id} not found.` if the member doesn't exist.
- If the member already has this same `user_id`: 200, no change (idempotent).
- If the member has a different `user_id`: 409 `This member is already linked to another user.`
- If another member already has this `user_id`: 409 `This user is already linked to another member.`
  Detect it with a query first **and** catch the unique-constraint violation on commit (race), both
  mapping to the same 409. Domain exceptions in `services.py`, like `DuplicateMemberEmailError`.
- Returns `MemberDetailSchema`.

`DELETE /members/{member_id}/user`: sets `user_id = NULL`. 404 if the member doesn't exist; 204
whether or not it was linked. Rate limit scope `unlink_member_user`, plus `require_roles`.

Do not validate `userId` against auth-server (separate DB); the staff app only offers real users.

## Stage 4: Internal accept-invite endpoint

Called by auth-server's `afterAcceptInvite` hook (see the auth-server handoff).

`POST /internal/member-links/accepted-invite`, body `{ "userId": str, "email": EmailStr }`, response
`{ "linked": bool, "memberId": int | null }`.

- **Auth is not the JWT.** Add `internal_api_token: SecretStr` to `ApiSettings` (env
  `INTERNAL_API_TOKEN`; required in staging/production, optional locally where the route is then
  disabled and returns 404). Compare the `X-Internal-Token` header with `secrets.compare_digest`;
  401 on mismatch. Put the router outside the JWT-protected routers and keep it out of the OpenAPI
  schema (`include_in_schema=False`).
- Logic, in one transaction: find members whose `lower(email)` equals the lowercased email **and**
  `user_id IS NULL`. Exactly one → set its `user_id`, `linked: true`. Zero or several → change
  nothing, `linked: false`. If `userId` is already linked to some member → change nothing,
  `linked: false`. Always 200; this endpoint must never make the invite acceptance fail.
- Per-IP rate limiting stays at the edge; the shared secret is the control here.

## Stage 5: Current member and `GET /me`

The link exists so this service can tell which member is behind a request (cross-repo spec, rule 9
and *The current member*). The JWT stays `{ sub, role }`; the member is looked up here, never
copied into auth-server. `docs/specs/small-group-leader-access.md` builds on this stage.

**Files:** `data/members/queries.py`, `data/members/services.py`, a new `api/current_member.py` (or
next to `jwt_auth.py`), a new `api/routers/me.py`, `api/schemas/`.

- `get_current_member(db, claims) -> Member | None`: the member whose `user_id == claims.sub`, or
  `None`. Expose it as a FastAPI dependency (`CurrentMemberDep`) for later routes. No user without
  a member is an error here (rule 2).
- `GET /me`, any authenticated role, default rate limit only. Response (`CamelModel`):
  `{ userId, role, member: { id, name } | null, leads: [{ smallGroupId, name, role }] }`.
  `userId`/`role` come from the claims. `leads` lists the member's **active** periods
  (`left_at IS NULL`) with role `leader` or `co_leader`, closed groups included, ordered by group
  name; empty when `member` is null. One query for the member, one for `leads` (or one joined
  query); don't load full group details.
- Try it in `/docs` with a token whose `sub` is linked (link one in Stage 3), one whose `sub`
  isn't, and one whose member leads a group and co-leads another.

## Stage 6: Docs

- `CLAUDE.md`: extend the Members DB bullet by one sentence: `user_id` is a cross-service
  reference with no FK, set only through `PUT/DELETE /members/{id}/user` and the internal accept
  endpoint, which require `admin`/`elder` and the service token respectively.
- `.env.example`: `INTERNAL_API_TOKEN`.
- `CLAUDE.md`: one sentence that the current member is resolved from the JWT `sub` through
  `members.user_id` (`get_current_member`, `GET /me`); the JWT carries no member id.
- `ROADMAP.md`: note that `require_roles` and `get_current_member` exist and Phase 9 (role gating,
  specified in `docs/specs/small-group-leader-access.md`) should reuse them.

## Not in this spec

- Looking up users in auth-server from this service; checking that `userId` exists.
- Clearing `user_id` when a user is deleted (D2 in the cross-repo spec).
- Role gating and leader scoping on the other routes: `docs/specs/small-group-leader-access.md`.
- Seeding linked members: seed data has no auth-server user ids to point to.
