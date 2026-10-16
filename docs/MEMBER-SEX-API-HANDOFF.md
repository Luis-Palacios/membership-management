# Member sex: column and API fields

Handoff spec for the membership-management side of **member sex**. Read the cross-repo spec
first: `../docs/specs/member-sex.md` (workspace folder `members-management/docs/specs/`); its
rules are referred to as *rule N*.

**One migration**: a nullable `members.sex` column with a CHECK constraint.

Work through it **stage by stage**, one reviewable commit per stage, on the **`member-sex`**
branch (the same name in every repo). Each stage must pass `uv run ruff check .` and
`uv run ty check`. There's no test runner yet: try it against the local API (`TestClient` with
the claims dependency overridden, as earlier handoffs did, or `fastapi dev`) and note in
*Decisions and deviations* what you tried and how.

Keep the existing conventions: routes call `data/members/services.py` directly, schemas are
`CamelModel`, the enum lives with its model (as `SmallGroupRole` does in
`data/small_groups/models/small_group_member.py`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Model, migration and seed | ⬜ | |
| 2. API fields | ⬜ | |
| 3. Docs | ⬜ | |

### Decisions and deviations

- [Anything decided during implementation, and how it was tried.]

## Stage 1: model, migration and seed

**Files:** `data/members/models/member.py`, `data/members/models/__init__.py`,
`data/migrations/versions/<rev>_add_member_sex.py`, `data/seed/members.py`.

- Add `class MemberSex(StrEnum)` with `MALE = "male"`, `FEMALE = "female"` next to `Member`, and
  export it from `data/members/models/__init__.py`.
- Add the column after `birth_date`, same pattern as `SmallGroupMember.role` (rule 3):

  ```python
  # VARCHAR + CHECK rather than a native Postgres ENUM, like small_group_members.role.
  sex: Mapped[MemberSex | None] = mapped_column(
      Enum(
          MemberSex,
          native_enum=False,
          create_constraint=True,
          length=10,
          name="sex",
          values_callable=lambda values: [v.value for v in values],
      ),
  )
  ```

- Migration: `uv run alembic revision --autogenerate -m "add member sex"`, then **review it**.
  Autogenerate adds the column but may not emit the CHECK constraint for a non-native enum on an
  existing table. Check with `uv run alembic upgrade head --sql` that the output has both the
  `ADD COLUMN sex VARCHAR(10)` and a `CHECK (sex IN ('male', 'female'))` constraint named by the
  naming convention (expected `ck_members_sex`). If the constraint is missing, add it by hand with
  `op.create_check_constraint(...)` (and drop it in `downgrade`). The column is nullable, with no
  default and no backfill (rule 2). Then `upgrade head`, `downgrade -1`, `upgrade head`, and
  `uv run alembic check`.
- Seed (`seed_members`): it already picks the given name from `FEMALE_GIVEN_NAMES` or
  `MALE_GIVEN_NAMES`. Keep that choice and set `sex` to match. Leave about 10% of members `None`
  (e.g. a `SEX_RATE = 0.9` next to `EMAIL_RATE`), as in real data. Draw the extra random number
  **after** the existing draws for that member, so names, emails and phones for a given seed are
  unchanged where possible; if they shift anyway, say so in the log.

## Stage 2: API fields

**Files:** `api/schemas/members.py`, `api/routers/members.py`, `data/members/services.py`.

- `MemberDetailSchema`: `sex: MemberSex | None` after `birth_date`; `_detail()` fills it.
- `MemberCreateSchema`: `sex: MemberSex | None = None`; `post_member` passes it, and
  `create_member(...)` gets a `sex: MemberSex | None` keyword.
- `MemberUpdateSchema`: `sex: MemberSex | None = None`. PATCH already applies only the sent
  fields, so `"sex": null` clears it and an absent `sex` leaves it alone. No change to
  `update_member`.
- **Not** in `MemberSummarySchema` (`GET /members`) or `MeSchema` (rule 4).
- Errors: anything other than `"male"`, `"female"` or `null` is FastAPI's standard 422. No new
  error message.

The shapes (camelCase on the wire):

```jsonc
// GET /members/{id}, POST /members (201), PATCH /members/{id}
{ "id": 162, "name": "Lucía Fernández", "email": "...", "phone": "...", "address": "...",
  "birthDate": "1994-03-14", "sex": "female", "userId": "...", "smallGroups": [ ... ] }

// POST /members body: sex optional
{ "name": "Lucía Fernández", "sex": "female" }

// PATCH /members/{id} body: set or clear
{ "sex": "male" }
{ "sex": null }
```

Try: create with and without `sex`; PATCH set, change, clear with `null`, and a PATCH without
`sex` leaves it; `"Male"`, `"other"` and `""` give 422; `GET /members` has no `sex`; the
OpenAPI page shows the enum.

## Stage 3: docs

- `CLAUDE.md`: one clause where the members DB is described (`members.sex` is VARCHAR + CHECK,
  `male`/`female`, nullable; a new value needs a hand-written migration).
- Tick this log. Mention in the final message that staff-app's `api/members-api/types.ts` must
  add `sex` (its handoff covers it).
