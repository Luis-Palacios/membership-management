# Leaders edit the email of an unlinked member

Handoff for the membership-management side. Rules: `../docs/specs/roles-and-permissions.md`
(workspace folder `members-management/docs/specs/`), rule 8.

One change, no migration: `PATCH /members/{id}` with `email` is 403 only when the member has a
`user_id` and the caller lacks `members: all`. An unlinked member in the caller's scope can have its
email changed with `members: update` alone. Out of scope is still 404; a duplicate email is still 409.

Branch **`leader-edit-member-email`** (same name in every repo).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Email check and docs | ✅ | (this commit) |

### Decisions and deviations

- A linked member keeps the 403; only the message changed, to say why.
- staff-app needs `userId` from `GET /members/{id}` (already in `MemberDetailSchema`) to hide the
  field for linked members.
- Tried with `TestClient` (claims overridden, local DB, rows deleted afterwards) as a leader with
  `members: update` + `smallGroups: view` leading a group with one unlinked and one linked member:
  email on the unlinked member 200; email on the linked member 403; a PATCH without `email` on the
  linked member 200; the same linked-member email change with `members: all` 200.
