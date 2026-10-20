# Edit own profile: `PATCH /me/member`

Handoff for the membership-management side of **edit own profile**. Read the cross-repo spec
first: `../docs/specs/edit-own-profile.md` (workspace folder `members-management/docs/specs/`);
rules are referred to as *rule N*. Needs auth-server's `ownProfile: ['update']` (its stage 1, done).

Branch **`edit-own-profile`**, one reviewable commit per stage. Each stage passes
`uv run ruff check .` and `uv run ty check`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. `PATCH /me/member` | [x] | see `git log` |
| 2. Docs | [x] | see `git log` |

### Decisions and deviations

- `_detail` in `routers/members.py` is now `member_detail` (public) and `routers/me.py` imports it,
  so both routes return the same `MemberDetail` without a copy.
- `MyMemberUpdateSchema` (`schemas/members.py`) has `extra="forbid"` and only the five fields.
  `name: Name | None = None` plus a field validator that rejects an explicit null, so the 422 comes
  from the schema (unlike `PATCH /members/{id}`, which checks in the route). The validator doesn't
  run when `name` is absent, so absent still means "leave alone".
- The route uses `require_permission("ownProfile", "update")` and `CurrentMemberDep`; no members
  scope. It calls `update_member` with `exclude_unset` changes. Email isn't in the schema, so
  `DuplicateMemberEmailError` can't happen and isn't handled.
- Rate limit `30/minute`, scope `update_my_member` (same as `update_member`, own counter).
- An empty body `{}` is a 200 that changes nothing and returns the detail. Left as is.
- Tried with `TestClient` (claims overridden, local DB, two `ZZ` rows deleted afterwards, none left):
  - linked user with `ownProfile: update`: all five fields set in one PATCH (name is stripped);
    `phone`, `address`, `birthDate` and `sex` cleared with `null` (name and email kept); `sex`
    alone leaves the rest.
  - 403 with no `perms`, and with `members: update`/`all` but no `ownProfile`.
  - 404 for a `sub` with no linked member.
  - 422: `email`, `userId` and `id` in the body (`extra_forbidden`), `name: null`, blank `name`,
    `sex: "other"`. The other member's row was unchanged after `{"id": <other>, ...}`.
  - rate limit: 429 after 30 requests in the minute (20 of the 32 in the last loop were 200s; the
    earlier calls had used the rest).
  - OpenAPI `MyMemberUpdateSchema` lists exactly those five properties, `additionalProperties: false`.
  - Not tried: a real JWT from auth-server (claims were overridden), so the `ownProfile` name in
    `perms` is taken from auth-server's handoff, not from a decoded token.

## Stage 1: `PATCH /me/member`

**Files:** `api/schemas/members.py`, `api/routers/me.py`, `api/routers/members.py` (rename only).

```jsonc
// PATCH /me/member, any subset of these; null clears all but name
{ "name": "Lucía Fernández", "phone": "8888-0000", "address": null, "birthDate": "1994-03-14", "sex": "female" }
// 200: same body as GET /members/{id} (MemberDetail, camelCase)
// 403 no ownProfile: update · 404 not linked · 422 unknown field (email, userId, id...), name null
```

## Stage 2: docs

`docs/ARCHITECTURE.md` (permissions bullet, role table, `user` exception) and the `CLAUDE.md` line on
authorization.

## For staff-app (not done here)

- Add `ownProfile` to the typed permission unions in `lib/auth/permissions.ts` (`update`), and gate
  the edit on `ownProfile: update` plus a linked member (`GET /me` has `member`); `pending` has none.
- Regenerate the API types (`api/members-api/types.ts`): the OpenAPI now has `PATCH /me/member`
  (operation `update_my_member`) and the `MyMemberUpdateSchema` body. The shape is ready to generate.
- Server action `PATCH /me/member` with the five fields; send `null` to clear phone, address,
  birthDate or sex; never send `email`, `id` or `userId` (422). Show 403/404/422 messages.
- Form: same validation as the member form (name 1-255 required; phone ≤ 20; address ≤ 255; sex
  `male`/`female`). After saving, refresh `GET /me` too, since `member.name` comes from it.
