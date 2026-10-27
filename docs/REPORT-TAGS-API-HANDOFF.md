# Report items, person tags and the person timeline

Handoff spec for the membership-management side of **report items, tags and the person timeline**.
Read the cross-repo spec first: `../docs/specs/report-tags.md` (workspace folder
`members-management/docs/specs/`); its rules are referred to as *rule N*. It builds on
`docs/PRAYER-FOLLOW-UP-API-HANDOFF.md` (shared endpoint, section threads),
`docs/GUEST-SMALL-GROUPS-API-HANDOFF.md` (guests, `PersonKey`, `guest_search_text`) and
`docs/INACTIVE-MEMBERS-API-HANDOFF.md`.

Two parts, two branches:

- **Part 1, `report-tags`.** The three report texts become lists of **items** that can **tag**
  members and guests. Stages 1–4 *expand* (new tables, new `sections` field next to the old text
  fields, both work); stage 5 *contracts* (drops the old fields and columns) and **waits until the
  staff app's Part 1 is deployed**.
- **Part 2, `person-timeline`.** `GET /members/{id}/timeline` and `GET /guests/{id}/timeline`.
  No migration beyond indexes.

> **No email, no notifications** (rules 13, 24). Report conversations Part 2 stays where it is.
> **No new permission**: auth-server doesn't change.

Work through it **stage by stage**, one reviewable commit per stage. Each stage must pass
`uv run ruff check .` and `uv run ty check` (and `uv run alembic check`, plus a `downgrade -1` /
`upgrade head` round trip, in migration stages), and be tried against the local API (`TestClient`
with the claims dependency overridden, as before) as each role: `admin`, `elder` (linked and
unlinked), `smallGroupLeader` (of a member group, of a guest group, out of scope, former leader),
`deacon` with no member, `user`. There's no test runner yet, so note in *Decisions and deviations*
what you tried and how. Use a scratch database for migration stages, not the dev one.

Keep the existing conventions: routes call `services.py` directly, `queries.py` builds `Select`s,
`results.py` holds `NamedTuple`s mapped with `all_as`, schemas are `CamelModel`, service errors are
domain exceptions the router maps to HTTP codes, "today" is `church_today()`, routes doing blocking
database work stay plain `def`, and every `SmallGroupMember`-style person reference is a
`member_id` **or** a `guest_id` with a `num_nonnulls(...) = 1` check (`PersonKey`).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| **Part 1 (`report-tags`)** | | |
| 1. Items and tags: migration, models, backfill | ✅ | `40f916a` |
| 2. Write and read `sections` (both shapes accepted and returned) | ✅ | `37d817c` |
| 3. Tag search | ✅ | `5e8a35d` |
| 4. Shared endpoint, section threads, seed | ✅ | `861ed6d` |
| *(staff app Part 1 deploys here)* | | |
| 5. Contract: drop the old text fields and columns, docs | ⬜ | |
| **Part 2 (`person-timeline`)** | | |
| 6. Timeline service and indexes | ✅ | `a9fa6f9` |
| 7. Timeline routes, seed check, docs | ✅ | `d2e2398` |

### Decisions and deviations

- **Stage 1.** Autogenerate emitted the checks and the named unique constraints itself (they're
  table args in `create_table`), so only the backfill is hand-written. The backfill imports
  `split_legacy_text` (a pure function, no models) rather than duplicating it. The section → column
  map is spelled out in the migration, not read from `ReportSection.report_attribute`, since stage 5
  removes that.
- **Stage 1.** Token-like text that isn't a person segment is broken apart (`@{member:1}` →
  `@ {member:1}`), in old texts and in text segments alike, so tags only ever come from person
  segments and the people table always matches the tokens. `-`, `*` and `1.` / `1)` markers need a
  space after them (`*urgent*`, `-5 °C`, `1.5` keep theirs); `–`, `•`, `·` don't.
- **Stage 1, tried** on scratch DB `rt-scratch` (seeded, then two reports edited to
  `"- a\n• b\n\n3) c"`, a blank praise, and `"*urgent* see @{member:1}\n1.5 million"`): items per
  section match a Python split of the old columns (50 / 36 / 21), no items for no-meeting reports,
  no people rows, `a`/`b`/`c` as three items, the blank gives none, the lookalike stays text.
  `alembic check` clean; `downgrade -1` drops both tables, `upgrade head` refills identically.
- **Stage 2.** Old-shape writes (no `sections`) aren't held to the 20-items limit: today's client
  can't know about it, and its texts are already capped at 1024 characters. Item length, tag count
  and the 20 items apply to `sections`. The schema only has loose caps (100 items, 200 segments,
  4096-character text segments) so the 422 texts come from the service, after empty items are dropped.
- **Stage 2.** The old columns are written from the items, people by full name, cut at 1024
  characters (their width; only tagged `sections` writes can get there). Reads derive the old fields
  from the items too, so a rename shows in them as well.
- **Stage 2.** `update_report` flushes the deleted items before inserting the new ones (the unit of
  work would insert first and trip the position constraint), and does it before touching the report's
  date, so a date clash still surfaces at commit as the existing 409.
- **Stage 2.** "Newly tagged" is per section, so moving an inactive member's tag to another section
  is a 422. `viewable` also needs `members: view` / `guests: view`, like the pages. Batched helpers
  `members_active_in_open_groups` and `guests_in_groups` decide it in at most two queries
  (`access.viewable_people`); the segment mapping lives in `api/report_items.py`, reused by stage 4.
- **Stage 2, tried** (`TestClient`, claims and current member overridden, scratch DB; a former
  co-leader of group 2 added): create with `sections` (member of the group, a guest of a guest group,
  a member of another group, a group-level item, a blank item dropped, whitespace collapsed); the old
  field in the same body ignored. `viewable`: admin, elder linked and unlinked all true; group 1's
  leader true for their member, false for the guest and the other group's member. 404 for a leader
  out of scope, the former leader, a guest-group leader and a deacon with no member; 403 for `user`.
  Old fields only: `"- uno\n• dos\n\n3) tres"` → three items, `"uno\ndos\ntres"` back. Re-sending an
  older report's items: identical items and old fields. Inactive member newly tagged → 422; already
  tagged then made inactive → 200; moved to another section → 422. 21 items, 11 tags, 1025 characters,
  an unknown guest → 422 with the contract texts; 20 items plus a blank one, 10 tags, 1024 characters
  → 200; a no-meeting body with `sections` → 422; `@{member:1}` typed as text stays text; the same
  person twice in an item → one people row. A rename shows in segments and the old field. Old fields
  of the 51 seeded reports against their columns: identical except where the stage 1 backfill
  dropped markers or blank lines (only the planted test texts in the seed).
- **Stage 3.** One SQL query ranks and limits (a `UNION ALL` of active members and guests, with
  `in_this_group` and `starts_with` columns), one more loads the rows' current groups. Name matching
  is factored out of the existing searches as `member_name_match` and `guest_name_match` (the latter
  is the guest search minus its phone part, still on `guest_search_text`). `tag_search_query` sits in
  `members/queries.py` next to `member_search_query`: `small_groups/queries.py` can't import the
  member queries (they import it). "Starting with" means the full name starts with `q`. The any-of
  permission is a local dependency (`require_permission` is all-of). A missing `q` is `[]`, like a
  short one.
- **Stage 3, tried:** elder in group 5, `kev` → the group's Kevin first, then the other three
  (a guest included) by name; a member-group leader finds both guests named Baldizón/Baldizon
  (accents, other guest groups) with `phoneLast4`; a guest in no group has `groups: []`; `ALVARO`
  finds Álvaro; the inactive seeded member never appears; 1 character, blank-padded 1 character and no
  `q` → `[]`; 101 characters → 422; `%_` matches nothing; `ra` → 10 rows, this group's block first;
  `ma` → names starting with it before the rest, inside and outside the group. 404 out of scope, for
  the former leader, a deacon with no member and a missing group; 403 for `user` and `pending`. Rows
  carry only `person`, `inThisGroup`, `groups`, `phoneLast4`.
- **Stage 4.** `section_has_items_query` replaces `section_text_query` in `conversation_queries.py`.
  The thread responses carry no section text (the panel reads it from report detail), so they don't
  change. `shared_reports_query` no longer selects the old columns: the entry's strings come from the
  items, like report detail's. `report_attribute` is now used only by the stage 2 legacy code in
  `services.py` (the conversation seeder looks at items instead), plus a comment in the stage 1
  migration.
- **Stage 4, seed.** Items go through `set_new_report_items` (the create path's validation). The
  text each report seeder already drew becomes the first, untagged item of its section, so the shared
  RNG's sequence is untouched and **every other seeded row is identical** to before (compared table
  by table, old columns aside); the extra tagged items use an RNG seeded by group name and date. Per
  held report: 1–3 prayer, 0–2 praise, 0–1 follow-up (half the drawn follow-ups become a tagged one);
  a tag is someone on the report, or 25% of the time a member of another group; guest groups'
  reports tag from their list, which is mostly guests. 184 items, 87 tags. Member-group reports can't
  tag guests yet (guests are seeded last); stage 7 revisits that for the timeline.
- **Stage 4, tried:** shared endpoint for five weeks as an elder, group 1's leader and a guest-group
  leader, against stage 3's code on the same DB: bodies identical except the added `sections`, and
  every old string equals its section's items joined. With the new seed, `viewable` per caller (the
  guest-group leader: their guest yes, another group's member no; a deacon with no member: no entries;
  `user`: 403). A section thread on a section with items whose old column was nulled starts; one with
  no items is 422 `This section is empty.`. `seed --reset` twice: identical dumps. Stages 2 and 3
  re-run on the new seed: all pass.
- **Stage 6.** The service takes the caller's observation audience as `observation_groups`
  (`None` = every group, else those ids) instead of claims, like `build_report_detail` takes booleans:
  the API layer computes it (stage 7) and `data/` imports nothing from `api/`. Range resolution and its
  three 422 messages (`TimelineRangeError`) live in the service too (`resolve_range`); the `latest`
  conflicts are a router check. Everything the person has is loaded for all dates in three queries
  (reports, periods, items), then visibility, the range and the group filter are applied in Python:
  `groups` and `earliestDate` look past the range anyway, and a person's reports are in the hundreds at
  most. One names query covers the items shown. `viewable` is left to the router, as in report detail.
  `counts` follow the rows returned, so with `latest` they cover just those rows.
- **Stage 6, indexes.** None added. The reports query finds the report ids as a `UNION` of two lookups
  (attendance by person, tagged by person) rather than an `OR`, so each uses its own index; `EXPLAIN` on
  the seeded scratch DB (`enable_seqscan = off`, the tables are too small to prefer an index) shows
  `ix_small_group_report_attendances_member_id` and `ix_small_group_report_item_people_member_id`, and
  the attendance join by `(report_id, member_id)` uses its unique index. The items query is the same
  `item_people` index.
- **Stage 6, tried** (service called directly on scratch DB `pt-scratch`, seeded; no routes yet): member
  17 (co-leads group 4, tagged from groups 1 and 4, two follow-ups): as an elder (`None`) all 8 rows and
  2 follow-ups; with audience `{4}` the group 1 follow-up row is gone and not counted (7 rows, 1
  follow-up) and `groups` is `[4]`; with `{1}` only group 1's follow-up and group 4's prayer and praise
  (3 rows, attendance null); with `{}` prayer and praise only. A report where they are on the list and
  tagged is one row. `latest=3` gives the newest three rows with null `from`/`to`; `smallGroupId` of a
  group with no rows gives no rows and unchanged `groups`; no-meeting reports are excluded by `held` in
  the queries (they have no attendance or items, so nothing seeded to see). Guest 9
  as an elder (observation and attendance rows, `role` member) and with an unrelated audience (items
  only). Range: future `to`, `from` after `to` and 732 days give the three messages, exactly 731 days
  passes, `to` 2026-10-15 defaults `from` to 2026-07-16 and 31 May to 1 March (month clamp).
- **Stage 7.** Both routes take `MemberScopeDep`, `GuestScopeDep` and `OptionalSmallGroupScopeDep`
  (chips need both scopes for `viewable`, the audience needs the group scope). The observation audience
  is `conversation_group_ids` as it is, not a new function: the spec's "same check conversations use",
  so it also needs `smallGroupReports: view`. Query parsing is one dependency
  (`get_timeline_params`, `api/person_timeline.py`): it resolves the dates through `resolve_range` and
  answers the `latest` conflicts, all 422 with a string `detail` (`latest` out of 1-10 and a malformed
  date are FastAPI's own 422). It runs before the 404, so a bad range on a missing member is 422. The
  person's own chip is always `viewable: true` (added to the set `viewable_people` returns, which for an
  inactive member under a leader's scope would otherwise be false). `GET /members/{id}/timeline` doesn't
  have the "your own member is always readable" exception of `GET /members/{id}`: the spec gives the
  person no access to their own timeline (rule 23).
- **Stage 7, seed.** Member-group reports are seeded before the guests exist, so they couldn't tag any:
  `seed_guest_tags_in_member_reports` runs right after `seed_guests` and adds one prayer or praise item
  tagging a guest to every third held member-group report (guests in id order, so all but one of the
  twelve get a tag from a member group; 11 items and tags added: 195 items, 98 tags). It draws nothing
  from the shared RNG; it re-sets those reports' items through `set_new_report_items` (after flushing
  the deletes, as `update_report` does), so their item ids change. Compared table by table against the
  stage 6 seed: every other table and every other column of `small_group_reports` identical; two
  `--reset` runs give identical items. The old text columns match the items of all 48 held reports
  (144 sections) in report detail, and the shared endpoint answers 200 with `sections` on every entry.
  The seed now gives: member 21 (member of group 1, supporter in guest group 6) tagged once from group 2;
  member 17 (co-leader of group 4) tagged from group 1; guest 8 (moved from guest group 6 to 7) tagged
  once from a member group. Seeded observations are only the absence notes on guests, so member
  timelines carry no `notes` (the elder-written notes are the staff app's to create).
- **Stage 7, tried** (`TestClient`, claims and current member overridden, scratch DB, seeded; ids from
  the seed): member 17 as an elder unlinked, an elder linked, group 4's leader (7 rows, group 1's
  follow-up gone and not counted), group 1's leader (404, out of scope), a deacon with no member (404),
  `user` (403), a missing member (404). `latest=3` (null `from`/`to`), `latest` 0 and 11 (422), `latest`
  with `from`, `to` or `smallGroupId` (422), `to` in the future, `from` after `to` and 2024-01-01 (the
  three `range` messages), `from=nope` (422), an exactly 2-year range (200), `smallGroupId` of a group
  with no rows (200, `groups` unchanged, no rows) and of group 4. Member 21 as an elder (16 rows from
  groups 1, 2 and 6, group 2's follow-up included) and as group 1's leader (7 rows, `groups: [1]`, the
  follow-up gone). Guest 9 as an elder and as group 7's leader; guest 8 as an elder (rows from groups
  4, 6 and 7) and as group 7's leader (group 6's rows hidden, group 4's praise item shown), group 6's
  leader (404, guest moved), a member-group leader (404), a deacon with no member (404), `user` (403),
  a missing guest (404). Row shape checked against the spec's contract (`from`/`to` keys, `attendance`
  and `observation` null when hidden, `submittedBy`, the person's own chip viewable).

## Who can do what

| Role | Write `sections` | `GET …/tag-search` | Timeline: attendance + observation | Timeline: prayer, praise | Timeline: follow-up |
| --- | --- | --- | --- | --- | --- |
| admin, elder | ✓ (any report they can edit) | ✓ | every group | every group | ✓ |
| smallGroupLeader, deacon | their groups' reports | their groups (scope) | groups they lead | any group | groups they lead |
| user, pending | — (403) | — (403) | — (403) | — (403) | — (403) |

Timeline access itself is the person's page access: `members: view` + members scope, or `guests:
view` + guests scope (404 outside). "Every group" for attendance and follow-up means
`sees_all_observations(claims)` (`smallGroups: all` + `smallGroupReports: viewObservations`), the
same check conversations use.

---

## Part 1: items and tags

### Data model

Two tables, owned by Alembic like the rest of the members DB. Models in
`data/small_groups/models/` (`small_group_report_item.py`, `small_group_report_item_person.py`),
exported from `models/__init__.py`.

**`small_group_report_items`**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int identity PK | Not stable across edits (stage 2 replaces a report's items). Don't anchor anything to it yet. |
| `report_id` | FK `small_group_reports.id`, `ON DELETE CASCADE`, indexed | |
| `section` | VARCHAR(16) + CHECK in (`prayer`, `praise`, `followUp`) | Reuse `ReportSection`. A new section needs a hand-written migration, like `role`. |
| `position` | SMALLINT, CHECK `>= 0` | Order inside the section, from 0. |
| `text` | TEXT, not null | The item with person tokens (below). Trimmed, non-empty. |

Unique `(report_id, section, position)`: name it explicitly
(`uq_small_group_report_items_report_section_position`); the `uq` naming convention uses only the
first column and would clash with a later constraint, as it did for section threads.

**`small_group_report_item_people`**: one row per person tagged in an item (an index of the
tokens, so the timeline and "who's tagged" are plain joins).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | int identity PK | |
| `item_id` | FK `small_group_report_items.id`, `ON DELETE CASCADE`, indexed | |
| `member_id` | FK `members.id`, nullable, indexed | |
| `guest_id` | FK `guests.id`, nullable, indexed | |

`CHECK num_nonnulls(member_id, guest_id) = 1` (`one_person`), unique `(item_id, member_id)` and
`(item_id, guest_id)` (the second named explicitly, as in `small_group_report_attendances`).

**Person tokens in `text`:** `@{member:198}` and `@{guest:45}`. The text never stores names, so a
rename carries through (rule 11). The people table always matches the tokens: the service writes
both from the parsed segments, never one without the other. Text that only looks like a token but
doesn't match `@\{(member|guest):\d+\}` is plain text.

**Segments** are the API shape (contract in the spec): `text` segments and `person` segments.
Put the conversion in one module, `data/small_groups/report_items.py`:

- `segments_to_text(segments) -> (text, people)`: joins text segments and tokens, collapses runs
  of whitespace to one space, trims; returns the person keys in order of first appearance.
- `text_to_segments(text, names) -> list[Segment]`: splits on tokens; `names` is a
  `PersonKey → name` map loaded once per response (no per-item queries).
- `split_legacy_text(text) -> list[str]`: rule 2 and 5's split: one item per line, drop leading
  `-`, `–`, `•`, `*`, `·` and `1.` / `1)` markers, trim, skip blanks. Used by the backfill, by
  old-shape writes (stage 2) and nowhere else.

### Stage 1: migration, models, backfill

1. Models and one migration. Autogenerate finds the tables; the checks, the explicitly named unique
   constraints and the backfill are hand-written.
2. **Backfill** in the same migration, in SQL or with a light table definition (not the ORM
   models): for each report with `held = true`, each of `group_prayer_request`,
   `group_praise_report`, `group_relevant_discussion` → `split_legacy_text` → one item per line,
   `section` from `ReportSection.report_attribute`'s mapping. No people rows: nothing is tagged
   (rule 5). No-meeting reports have no texts and get no items.
3. **Downgrade** rebuilds nothing: the old columns are still there in Part 1 (stage 5 drops them),
   so it just drops the two tables. Note it in the migration's docstring.
4. `data/models.py` imports the new models (otherwise autogenerate drops the tables later).

Try: on a scratch DB with the seed, count items per section against a Python split of the old
columns; a text with `"- a\n• b\n\n3) c"` gives `a`, `b`, `c`; blank and null texts give no items;
`alembic check` clean; downgrade and upgrade round trip.

### Stage 2: write and read `sections`

**Writes** (`HeldReportBodySchema`, create and edit):

- New optional `sections: ReportSectionsInput | None = None` with keys `prayer`, `praise`,
  `followUp`, each a list (max 20) of `{ segments: list[SegmentInput] }`. `SegmentInput` is a
  discriminated union on `type`: `{ type: "text", text: str }` or `{ type: "person", person: {
  type: "member" | "guest", id: int } }`.
- When `sections` is sent it **wins**, and the old fields in the same body are ignored. When it's
  absent, the old three fields are split with `split_legacy_text` (one item per line, no tags), so
  today's staff app keeps working unchanged.
- Validation, in the service (domain exceptions → router):
  - Item text (after `segments_to_text`) at most 1024 characters, at most 10 people per item, at
    most 20 items per section (rule 3) → 422 `Too many items or tags in {section}.` /
    `An item in {section} is too long: items can be up to 1024 characters.`. Empty items are dropped silently (rule 2).
  - Every tagged person exists → 422 `Unknown person to tag.`
  - A **newly** tagged member must be active (rule 7) → 422 `{name} is inactive and can't be
    tagged.` "Newly" = not already tagged in the same section of this report before the edit, so
    re-saving an older report never fails because someone left the church.
- `create_report` / `update_report` replace the report's items (delete the old ones, insert the new
  ones with positions 0…n) in the same transaction as the rest of the report. Keep the old columns
  in step while they exist: write each section's items joined by `\n`, tokens replaced by full names
  (`_legacy_text(items, names)`), so anything reading them still sees the content.
- No-meeting bodies are unchanged (`extra="forbid"` already refuses `sections` there).

**Reads:**

- `ReportDetailSchema` gains `sections: ReportSectionsSchema` (`prayer`, `praise`, `followUp`:
  lists of `{ id, segments }`), built in `build_report_detail` with **one** query for the report's
  items and one for the names of the people they tag. Person segments carry `name` (current) and
  `viewable` (rule 12): `True` with `members: all` / `guests: all`, otherwise whether the person is
  in the caller's `MemberScope` / `GuestScope`. Compute it once per response for the set of people
  on the page, not per segment.
- The old three text fields stay in the response (now derived from the items, as written above).
- Who sees `sections`: whoever sees the report today (the texts were never observation-gated, rule 3
  of prayer & follow-up).

Try: create with `sections` (a member and a guest tagged, a group-level item, an empty item that
gets dropped), read it back (segments, names, `viewable` for an elder, for the group's leader on a
member of their group and on a member of another group); create with the old fields only (one item
per line comes back); edit an older report re-sending its untagged items; tag an inactive member
(422) and re-save a report where an already-tagged member has since become inactive (200); 21 items,
11 tags, a 1025-character item (422); an unknown guest id (422); a no-meeting body with `sections`
(422 as today); rename a tagged member and read again (new name). Compare the old-field responses
before and after for reports with no tags: identical text (line breaks may differ where the backfill
split lines: note it).

### Stage 3: tag search

`GET /small-groups/{id}/tag-search?q=` in `api/routers/small_group_reports.py` (it's about writing
that group's reports), service in `data/small_groups/services.py`, queries next to the member and
guest searches.

- Permission: `smallGroupReports: create` **or** `update` (either is enough), plus the small group
  scope (404 outside). A closed group's reports are read-only, so its tag search returns `[]`
  (not 409).
- `q` trimmed; under 2 characters → `[]`. Max 100 characters.
- Searches **active members** (any group or none) and **guests**, church-wide (rule 10), with the
  same matching the existing searches use (`member_search_query`'s name match; for guests
  `guest_search_text` and its trigram index, never `unaccent()` directly). Name only: no phone or
  email matching here.
- Ranking: people active in this group first (`inThisGroup`), then names starting with the query,
  then the rest, then name. At most 10 rows in total.
- Row: `person` (`{ type, id, name }`), `inThisGroup`, `groups` (the person's **current** open
  groups: `id`, `name`, `audience`, `role`), `phoneLast4` (guests only; digits only, last 4, null
  when none; null for members).
- Nothing else: no email, address, observations, attendance or status (rule 10).

Try: an elder in any group; a leader of a member group finds a guest of another group by name
(new reach, rule 10: the reason is in the spec); a leader out of scope (404); `user` (403); a member
who is inactive never appears; `Pab` with someone in this group and two elsewhere (this group's
first); accents and case (`jose` finds José); a guest in no group (`groups: []`).

### Stage 4: shared endpoint, section threads, seed

- **`GET /small-group-reports/shared`:** each entry gains `sections` (same shape as report detail,
  with `viewable`). One items query and one names query for the whole week, not per entry. The old
  `prayer` / `praise` / `followUp` strings stay until stage 5, derived from the items. An entry is
  listed in a section when that section has items.
- **Section threads:** `section_text_query` becomes "does this section have an item"
  (`section_has_items_query`); the 422 text `This section is empty.` is unchanged. Starting a
  thread on a section that has items but whose old text column happens to be null must work.
  `ReportSection.report_attribute` is now only used by the stage 2 legacy sync; remove it in stage
  5.
- **Seed** (`data/seed/`): write items through the same service helpers, with tags. For each held
  seeded report: 1–3 prayer items, 0–2 praise, 0–1 follow-up; about half the items tag one roster
  person of that report, some tag someone from another group, and guest groups' reports tag guests.
  Deterministic, as now (two `--reset` runs give identical rows).

Try: the shared endpoint's body against stage 3 for five weeks (only `sections` added); a section
thread on a section with items, and 422 on one without; seed twice and compare.

> **Stop here.** Stage 5 waits until the staff app's Part 1 is deployed (cross-repo spec, *Deploy
> order*). Say so in your final message.

### Stage 5: contract

Only after the staff app sends `sections` and reads `sections` in production.

- Drop the three fields from `HeldReportBodySchema`, `ReportDetailSchema` and the shared entry, and
  the `_legacy_text` sync. Drop `ReportSection.report_attribute`.
- Migration: drop `group_prayer_request`, `group_praise_report`, `group_relevant_discussion` from
  `small_group_reports`. **Downgrade** re-creates them and fills them from the items (joined by
  `\n`, tokens replaced by full names), so a rollback keeps the content.
- Docs: `docs/ARCHITECTURE.md` (*Small group reports*: items and tags, the token format, the
  tag-search row in the role × route table), `CLAUDE.md` (one line under small group reports:
  items, tokens, `report_items.py`), and a pointer under the title of
  `docs/SMALL-GROUP-REPORTS-API-HANDOFF.md` and `docs/PRAYER-FOLLOW-UP-API-HANDOFF.md`.

Try: the round trip on a scratch DB (downgrade gives back the texts); `alembic check`; every report
route for every role, comparing bodies with stage 4 minus the removed fields.

---

## Part 2: the person timeline

### Contract

`GET /members/{id}/timeline` and `GET /guests/{id}/timeline` (router: `members.py` and `guests.py`,
declared before any `/{id}/…` route that could shadow them). Response shape in the cross-repo spec.

Query parameters:

| Param | Default | Rules |
| --- | --- | --- |
| `from` | `to` minus 3 months plus 1 day | ISO date. 422 if after `to`. |
| `to` | church today | ISO date. 422 if in the future. 422 if `to - from` is more than 731 days. |
| `smallGroupId` | none | Only rows of that group. A group with no visible row just gives no rows (not 404). |
| `latest` | none | 1–10. Newest N visible rows, any date and group; `from` and `to` are null in the response. 422 together with `from`, `to` or `smallGroupId`. |

### Stage 6: timeline service and indexes

Service `get_person_timeline(session, person: PersonKey, *, claims, member_scope_or_guest_scope,
from_, to, small_group_id, latest)` in a new `data/small_groups/timeline_services.py`, queries in
`timeline_queries.py`. Rows are **held** reports where the person:

- has an attendance row (`small_group_report_attendances`), **or**
- is tagged in an item (`small_group_report_item_people` → items → report).

Visibility per row (rule 23), decided in SQL where it's cheap and in the service otherwise:

- **Attendance and observation** are visible when the caller is in that report's observation
  audience: `observations_visible_to(sees_all_observations=…, leads_group=…)`, where "leads group" is
  the caller's led groups (`get_led_small_group_ids` plus led guest groups). `role` comes from the
  person's group period covering the meeting date (as the report detail does); null when none.
  `observation` is omitted when empty, with the report's submitter as `submittedBy`.
- **Prayer and praise items** that tag the person: visible to anyone who passed the endpoint's scope.
- **Follow-up items**: the same audience as attendance and observations: every group with
  `sees_all_observations(claims)`, otherwise only reports of groups the caller leads or co-leads
  (rule 23). Follow-up items from other groups' reports never appear, and never count.
- Only items that tag **this** person, ordered by section (`prayer`, `praise`, `followUp`) then
  position. Segments as in Part 1 (one names query for the whole response; the person themselves
  gets `viewable: true` only if the caller can open their page, which they can, since they're here).
- A row with no visible attendance and no visible item is dropped.
- Order: `meeting_date` desc, then report id desc.

`counts` cover the range and group, after visibility: `notes` (rows with a visible observation),
`prayer`, `praise`, `followUp` (items). `groups`: every group with at least one visible row, **any
date** (it fills the group filter), by name. `earliestDate`: the oldest visible row's date, any
group, null when none.

Indexes: `small_group_report_item_people.member_id` / `guest_id` exist from stage 1;
`small_group_report_attendances` already indexes `member_id` and `guest_id`. Add a migration only if
`EXPLAIN` on the seeded DB shows a sequential scan on reports for one person (it shouldn't); note
the plan in *Decisions*.

### Stage 7: routes, seed check, docs

- `GET /members/{id}/timeline`: `members: view` + `MemberScopeDep` (404 outside, same message as
  the member route). An inactive member's timeline is readable by whoever can read the member.
- `GET /guests/{id}/timeline`: `guests: view` + `GuestScopeDep`.
- Range errors → 422 with `range` in the message: `The range can't end in the future.`, `The range
  must start on or before its end.`, `The range can't be longer than 2 years.`
- Seed: check the seeded data gives a useful timeline (a member in two groups, tagged once from a
  third; a guest moved between guest groups and tagged from a member group). Adjust the tag seeding
  from stage 4 if it doesn't.
- Docs: `docs/ARCHITECTURE.md` (role × route rows, a *Person timeline* entry with the visibility
  rules), `CLAUDE.md` one line.

Try: Lucía-like member (co-leader in one group, leader in another, tagged from a third) as an
elder (everything, follow-up included), as the leader of one of her groups (attendance and notes
and follow-up only from that group, prayer and praise from all three; a follow-up item tagging her
from a group the leader doesn't lead is missing and not counted), as a
leader out of scope (404), as `user` (403); a guest as an elder and as their guest group's leader
(rows from their previous guest group hidden); `latest=3`; each range error; a 2-year range;
`smallGroupId` of a group with no rows (empty, 200); a no-meeting report never appears; a report
where she's both on the list and tagged is **one** row.

## Not in this handoff

- Notifications of any kind, export, printing, LLM suggestions (spec rule 25).
- Stable item ids across edits, item-level threads or "answered" flags: later, and they'll need
  `update_report` to diff items instead of replacing them.
