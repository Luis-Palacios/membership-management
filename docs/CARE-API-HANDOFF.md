# Care and the care log

Handoff spec for the membership-management side of **the care log** (Part 1) and **care**
(*acompañamiento*, Part 2). Read the cross-repo spec first: `../docs/specs/care.md` (workspace
folder `members-management/docs/specs/`). Its rules are referred to as *rule N*, its *Data model*
and *Contracts* sketches are the starting point, and this handoff fixes the details. It builds on
the person timeline (`REPORT-TAGS-API-HANDOFF.md` Part 2, `INACTIVE-GUESTS-API-HANDOFF.md` Part 2:
typed entries), report conversations (`REPORT-CONVERSATIONS-API-HANDOFF.md`, read marks and
`last_activity_at`), section threads (`PRAYER-FOLLOW-UP-API-HANDOFF.md`) and guests, all on `main`.

What this adds:

- **Part 1, the care log** (rules 1–13): a new `data/care/` domain with care log entries (a call,
  messages, a meeting, a visit, something someone told us, a note; done, planned or cancelled)
  about members and guests, their routes, a `careLog` timeline source, and *Coming up*.
- **Part 2, care** (rules 14–39): cares with people, owners, status, an *Urgent* flag, a next
  check-in, a stream (entries inside the care plus events), read marks, links to the reports,
  items, threads and entries they came from, the Care lists and counts, prayer summaries, a `care`
  timeline source, and owner options.

Work through it **stage by stage**, one reviewable commit per stage. Part 1 is branch
**`feature/care-log`** (stages 1–5); Part 2 is branch **`feature/care`** (stages 6–12), started from
`main` once Part 1 is merged. The same names are used in every repo.

- **Checks.** Each stage must pass `uv run ruff check .` and `uv run ty check` (and
  `uv run alembic check`, `downgrade -1` + `upgrade head` round-trip in the migration stages).
- **Roles to try.** Try each stage against the local API (`TestClient` with the claims dependency
  overridden, as before) as each role, with `GUEST_GROUPS_ENABLED` on:
  - `admin`, and `elder` linked and unlinked
  - `smallGroupLeader` leading a member group, one leading a guest group, one leading nothing
  - `deacon` with no member
  - `user`
- **No test runner yet,** so note in *Decisions and deviations* what you tried and how.
- **Don't touch the dev database:** use a scratch one, as in earlier features.

**Depends on:**
- auth-server stage 1 (`careLog`) before stage 2 can be tried as a real role, and auth-server
  stage 2 (`care`) before stage 7. If they aren't in the JWT yet, say so and stop at the end of the
  migration stage. Don't stub permissions in committed code.
- **Stage 11 (owner options)** needs auth-server's `GET /internal/users/with-permission` from report
  conversations Part 2 (`REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`). The cross-repo spec puts all of
  care after that work; if the endpoint still isn't on `main` when stage 11 starts, say so and stop.

Keep the existing conventions:
- Routes call `services.py` directly; `queries.py` builds `Select`s; `results.py` holds `NamedTuple`s
  mapped with `all_as`.
- Schemas are `CamelModel`.
- Service errors are domain exceptions the router maps to HTTP codes; 409s and 422s that staff-app
  tells apart carry a `code` through `CodedHTTPError` (`api/coded_errors.py`).
- "Today" is `church_today()`.
- Routes doing blocking database work stay plain `def`.
- Enums are VARCHAR + CHECK (new values need a hand-written migration).
- People are a `PersonKey` (`member_id` or `guest_id`, exactly one, CHECK), as for tags and
  conversations.
- `user_id` columns are plain strings with no FK (auth-server is another database).

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| **Part 1, branch `feature/care-log`** | | |
| 1. Migration, models, seed (care log) | ✅ | `ccfede2` |
| 2. Care log routes, people search, visibility | ✅ | `a90a8b4` |
| 3. `careLog` timeline source | ✅ | `e3acc5c` |
| 4. Coming up | ✅ | `a9975a6` |
| 5. Docs (Part 1) | ✅ | `0e167a6` |
| Review fixes (stages 1–4) | ✅ | the commit "Fix care log review findings" (see `git log`) |
| **Part 2, branch `feature/care`** | | |
| 6. Migration, models, seed (care) | ⬜ | |
| 7. Access, create, read, edit, status, owners, read marks | ⬜ | |
| 8. Entries inside a care, check-ins, links, moving entries in | ⬜ | |
| 9. Care lists, counts, prayer summaries | ⬜ | |
| 10. `care` timeline source and linked-care lookups | ⬜ | |
| 11. Owner options | ⬜ | |
| 12. Docs (Part 2) | ⬜ | |

### Decisions and deviations

- **Branch names:** the handoff first said `care-log` and `care`; a workspace hook only allows
  `feature/`, `fix/` or `chore/` + kebab-case, so they are `feature/care-log` and `feature/care`
  (the spec's own "Branch name in every repo" line says the same, to be read with the prefix).
- **Stage 1, tried:** against the scratch database `care_scratch` on `my-postgres` (created by hand,
  dropped at the end of Part 1): `alembic upgrade head`, `alembic check` (clean), `downgrade -1` +
  `upgrade head` + `check` (clean), then `python -m membership_management.data.seed --reset` (six
  entries: see the seed). Enums use SQLAlchemy `Enum(native_enum=False, create_constraint=True)`, so
  the checks are named `ck_care_log_entries_<kind|status|meeting_mode|visibility|source_kind>`.
- **Stage 1, schema choices beyond the handoff:** `care_log_entry_revisions.text` is nullable (a plan
  with no purpose gets one by an edit); `text`, `heard_from`, `others` and `cancel_reason` also have
  length CHECKs; `source_matches_kind` requires, for `attendance`, exactly one of
  `source_member_id` / `source_guest_id` (those columns have no cascade, so they stay after the report
  is deleted while `source_report_id` goes null); `section` needs its `source_section`; `conversation`
  needs only its id column to be null or set. (The first version anchored items by id, which a report
  edit breaks: replaced by `section`, see *Review fixes*.)
- **Stage 1, seed:** `data/seed/care.py` runs last and draws no random numbers. The made-up elders are
  the conversations seeder's (`seed-elder-N`), found through their comments; the leaders have
  `seed-user-<member id>` ids. No account matches those, so every seeded entry shows as someone else's
  whoever signs in. The guest's visit is by the leader of the guest group the guest is in.
- **Stage 2, shape:** `data/care/` holds `access_rules.py` (`CareLogViewer`: pure data),
  `queries.py` (`care_log_visible_condition(viewer)`, the one SQL definition of rule 8),
  `services.py` and `results.py`; the API side is `api/care_access.py` (`CareContext`, built from the
  claims and the existing `MemberScope` / `GuestScope` / small group scope), `api/care_log.py`
  (`entry_schemas`, the `CareLogEntrySchema` builder the timeline reuses), `api/schemas/care_log.py`
  and `api/routers/care_log.py`. Deviation: there is no separate Python `care_log_visible(...)` twin.
  The single-entry check (`entry_visible`) runs the same SQL condition on one id, so the two can't
  disagree.
- **Stage 2, one touch outside the care code:** `data/small_groups/services.py`'s `_phone_last4` is
  now `phone_last4`, so the people search shares it. Nothing else of the existing code changed in the
  routes; the timeline routes change in stage 3.
- **Stage 2, validation codes** (422 body `{ detail, code }`, through `CodedHTTPError`): finer than the
  handoff's five. `kind_status`, `date`, `text`, `others`, `heard_from`, `meeting_mode`, `people`,
  `participants`, `reason` (cancel), `status` (PATCH changing it), `source` (PATCH sending one, or a
  section source without report or section), `kind` and `visibility` (PATCH sending null).
  Length limits aren't pydantic `max_length`, so a too-long text is a coded 422, not FastAPI's list.
  `heardFrom` is required for a `heard` entry (rule 1; see *Review fixes*). 404 for a person or source outside the caller's reach; an inactive person is 422 `people`
  (checked after the scope, so it tells nothing about people out of scope). 409 `link` (no linked member,
  create only) and 409 `not_planned` (complete or cancel of something not planned). 403 `author`.
- **Stage 2, decisions:** the write routes (create, edit, delete, complete, cancel, people search) need
  `careLog: create`, the reads `careLog: view`. Edit takes any field but the status and the source; a
  changed kind must keep the entry consistent (send `meetingMode: null` when leaving `meeting`, `heardFrom:
  null` when leaving `heard`). A participant completes or cancels only an entry they can see (rule 3: being
  a participant grants no access), so a `private` plan of an elder "with" a leader is not the leader's to
  complete. Editing an entry never changes its people to anyone out of scope; people already on it stay
  even if they later left the caller's scope. A text change writes a revision even when the entry had no
  text yet (a plan without purpose: revision text null); completing a plan keeps its purpose as a
  revision. `people-search` returns `{ person, groups, phoneLast4 }` (the tag search's shape without
  `inThisGroup`, which has no meaning without a group), min 2 characters, at most 10, inside the caller's
  members / guests scope (`careLog: all` searches everyone), active people only.
- **Stage 2, sources:** the body's `source` is `{ kind: "attendance", reportId, memberId | guestId }`,
  `{ kind: "section", reportId, section: "prayer" | "praise" | "followUp" }` or
  `{ kind: "conversation", conversationId }`. Attendance rows, the `followUp` section and threads need
  the caller's observation audience, `prayer` and `praise` only the group's scope (the same rule as
  opening that report), and the report must be submitted; otherwise 404. In a response, `source` is null (none),
  `{ visible: false, gone: false }` with no ids (the caller can't open it) or `{ gone: true }` (deleted).
- **Stage 2, tried** (`TestClient`, `get_current_claims` overridden, scratch DB `care_scratch` migrated
  and seeded, `GUEST_GROUPS_ENABLED` not needed for the care log), 132 checks, all passing. Roles, with
  perms as `statements.ts` computes them: elder (linked, `seed-elder-1`) and elder unlinked (both with
  `careLog: all`; `admin` has the same perms); `smallGroupLeader` leading group 4 and its co-leader;
  one leading group 2; one leading guest group 7; one leading guest group 6; a member leading nothing;
  `deacon` with no member; `user`. Read the six seeded entries as each (elder: all six; group 4's leader:
  the `leaders` ones about his member, not the elders-only one nor the guest's; group 2's leader and the
  one leading nothing: none; the guest group's leader: only the guest's; the other guest group's leader:
  none; deacon with no member: none; `user`: 403). People search per role. Create as a leader about own
  member (201), about someone in another group (404), about a guest of a group they don't lead (404),
  the guest's leader about the guest (201), an elder about any member and a guest, an inactive member
  (422 `people`), unlinked caller (409 `link`), `user` (403), and every 422 above. Visibility: a leaders
  entry is seen by the co-leader and elders, not by another group's leader; a private one only by its
  author and elders; a person leaving the group takes someone else's entry out of the leader's sight on
  the next request and it comes back when they return. Edit (revision kept and never returned, other
  person 403 `author`, hidden 404, status change 422), soft delete (row kept, 404 for everyone),
  complete (participant, without text 422, future date 422, twice 409) and cancel (participant, again
  409, no body), sources of each kind in and out of scope, and a report deleted: the entry stays and the
  source says `gone`.

- **Stage 3, shape:** the sources stay in `data/small_groups/timeline_services.py` (the "move to
  `data/timeline/`" option was not taken: three sources still fit, and moving them would touch
  Part 1's review for nothing). `_care_log_source` sits between status and report in `_SOURCES`, so on a
  date: status changes, then care log entries, then reports (newest first inside a kind). Its SQL is
  `person_timeline_care_log_query` in `data/care/queries.py`, over the same
  `care_log_visible_condition` as the routes. `get_person_timeline` gains `care_viewer` and `today`;
  `timeline_schema` gains the `CareContext`. A timeline entry is
  `{ "kind": "careLog", "date": "2026-11-19", "entry": CareLogEntrySchema }`, the date being the
  entry's `occurredOn`; `counts` gains `careLog` (entries listed, plans ahead included; the four report
  counts are unchanged). `earliestDate` counts care entries. With `latest`, plans ahead are listed too
  and, being the newest dates, come first.
- **Stage 3, tried:** a dump of every timeline (9 roles x 6 people x 5 parameter sets: none, `latest=3`,
  `latest=10`, a wide `from`/`to`, `smallGroupId=4`; 270 requests, 90 of them 200) before and after, on
  a freshly seeded scratch DB: with `careLog` entries and `counts.careLog` removed, all 90 responses are
  identical (for `latest`, the report and status entries are the prefix of the old list that fits). Then
  by hand (16 checks): elder sees all five entries about the seeded member, the leader of her group four
  (not the elders-only one), another group's leader gets 404 on the member; picking a group hides them;
  a range with nothing in it still lists the plan ahead; cancelled and deleted entries are left out; the
  guest's visit shows for the elder and the guest group's leader, 404 for another leader; on a shared
  date the care log entry goes above the report.

- **Stage 4, shape:** `GET /care-log/coming-up` (`careLog: view`) answers
  `{ "pastDue": [CareLogEntrySchema], "upcoming": [CareLogEntrySchema] }`: planned, not deleted,
  author or participant, and visible to the caller (a participant of a plan they can't see, such as an
  elder's `private` one, doesn't get it). `upcoming` is today through today + 7, by date then time;
  `pastDue` is before today, oldest first. Declared before `/{entry_id}`. No paging.
- **Stage 4, a bug in stage 1 found and fixed here:** cancelling a plan with no purpose hit the check
  `status = 'planned' OR text IS NOT NULL` (500). It is now `status <> 'done' OR text IS NOT NULL`
  (`ck_care_log_entries_text_when_done`), changed in stage 1's migration in place (the branch isn't
  merged or deployed anywhere); the scratch DB went through `downgrade -1` + `upgrade head` + `alembic
  check` again.
- **Stage 4, tried** (14 checks): elder (author of both seeded plans) gets the past-due call and the
  meeting ahead; the leader who is a participant of both gets the same; a co-leader, another group's
  leader, an unlinked elder (author is matched by user id, the seeded ones belong to another) and a deacon
  with no member get empty lists; `user` 403. The horizon (a plan today and on day 7 listed, day 8 not),
  ordering by date then time, and completed, cancelled and deleted plans leaving the list.

- **Stage 5, docs:** `docs/ARCHITECTURE.md` has a *Care log* section and the routes in the role x route
  table (and one sentence in *Person timeline*); `CLAUDE.md` one bullet. `docs/ROADMAP.md` lists no
  features, so it is untouched. **Part 1 is done in this repo.** Others: staff-app needs the `careLog`
  permission names in its typed unions (auth-server already ships them in `perms`; a session or JWT
  minted before that has no `careLog`, so sign in again), the schemas above (`CareLogEntrySchema`, the
  timeline's `careLog` entry and `counts.careLog`, `coming-up`, `people-search`) and the error codes.
  Part 2 starts from `main` as `feature/care` once this is merged; it makes `visibility` nullable and adds
  `care_case_id` as the handoff says.

- **Review fixes (stages 1–4), in one commit:**
  1. *The person never sees it (rule 8).* In `care_log_visible_condition`, for a viewer without
     `careLog: all` who has a linked member, the `leaders` branch also requires that none of the entry's
     people is the viewer's own member; the author branch is untouched. `careLog: all` keeps seeing
     everything (decided: "only for leaders"). Lists, single entry, timeline, *Coming up* and the
     complete / cancel 404 all follow, being the same condition. Tried: an elder logs a `leaders` plan
     about a co-leader with him as participant: he gets 404 on GET and on complete, nothing on his own
     member timeline or in his coming-up, the group's other leader and the elder see it, and he sees his
     own entry about himself as its author.
  2. *Section sources (rule 12).* `item` is replaced by `section`: `source_report_id` (SET NULL) plus
     `source_section` (`prayer` | `praise` | `followUp`, CHECK as in `report_conversations.section`);
     `source_item_id` and its FK and index are gone; kinds are `attendance`, `section`, `conversation`
     (as the spec's `care_case_links`, which Part 2 mirrors). Body `{ kind: "section", reportId, section }`
     (422 `source` without either); response `source` keeps its fields and adds `section`.
     Visibility: `followUp` needs the observation audience, `prayer` and `praise` the report's group in
     the caller's scope, the report submitted (the rule for opening that report, which is narrower than
     the timeline's "prayer and praise tags from any group", since the link opens the report). Stage 1's
     migration was edited in place (unmerged), then `alembic check` and `downgrade -1` + `upgrade head`
     again; the seed's follow-up entries are `section` / `followUp` of the report. Tried: a section
     source survives every item of the report being deleted, and `gone` follows a deleted report.
     Note `alembic check` doesn't compare the non-native enum CHECKs, so the `source_kind` list was
     checked by seeding. Replaces the "known limit" of stage 1.
  3. *Complete / cancel race.* `_lock_planned` takes `SELECT ... FOR UPDATE` on the row, reloads it and
     only then requires `planned` (409 `not_planned` otherwise), so a complete racing a cancel, or two
     completes, can't both win. (`session.refresh(..., with_for_update=True)` is refused by Postgres
     with the eager outer join of the author, hence the separate locking select.) Tried with two
     sessions and a thread: the cancel waited on the lock, then lost; the outcome text stayed.
  4. *`heardFrom` required for `heard`* (1–200 after trimming): 422 `heard_from` on create, and on an
     edit that leaves a `heard` entry without it (blank, or kind changed to `heard` without it). The
     earlier "not required" deviation is withdrawn.
  5. *Participants.* Recorded: they get no access (rule 3); *Coming up* and complete / cancel only for
     entries they can already see. staff-app should warn when a picked participant can't see the entry:
     `participants[].sees` in `CareLogEntrySchema` says it. It is computed by the same
     `care_log_visible_condition` for that participant's own user (`members.user_id`; false when the
     member has no user), assuming `careLog: view` without `all` and the scope of the groups they lead
     today (permissions of another user aren't known here; an elder participant is therefore shown as
     not seeing a `private` entry although they would). Cost: two small queries per distinct participant
     and one per (entry, participant); participants are at most 10 and *Coming up* is short, so it was
     kept on every response rather than on a separate route.
  6. *Nits.* Stage 5's hash is `0e167a6` (above). `canEdit` and `canComplete` are false without
     `careLog: create` (the write routes would 403). The 422 `kind` and `visibility` codes (PATCH sending
     null) are listed above. Index: `ix_care_log_entries_live` (partial on `deleted_at IS NULL`) is
     dropped, `ix_care_log_entries_occurred_on_desc` kept: the partial one covered the same column and
     deleted rows are rare, and the descending one is what the newest-first timeline and lists order by.
  Tried again: `try_care` 153 checks (was 132), `try_timeline` 16, `try_coming` 14, and the 270-request
  timeline dump still identical with the care entries removed.

---

# Part 1: the care log (branch `feature/care-log`)

## Stage 1: migration, models, seed

New domain package `data/care/` (`models/`, `queries.py`, `services.py`, `results.py`), imported in
`data/models.py`.

**Enums** (`StrEnum`, VARCHAR + CHECK):

| Enum | Values |
| --- | --- |
| `CareLogKind` | `call`, `message`, `meeting`, `visit`, `heard`, `note` |
| `CareLogStatus` | `done`, `planned`, `cancelled` |
| `MeetingMode` | `in_person`, `online` |
| `CareLogVisibility` | `leaders`, `private` |
| `CareLogSourceKind` | `attendance`, `section`, `conversation` (was `item`: see *Review fixes*) |

**`care_log_entries`:**
- `kind`, `status`, `meeting_mode` (null unless `kind = meeting`, CHECK).
- `occurred_on` (date, NOT NULL), `occurred_at_time` (time, null).
- `text` (null only while `planned`, CHECK `status = 'planned' OR text IS NOT NULL`).
- `heard_from` (≤ 200, null unless `kind = heard`), `others` (≤ 200, null).
- `visibility` (NOT NULL in Part 1; stage 6 makes it nullable for entries inside a care).
- `author_user_id`, `author_member_id` → `members.id`.
- Source (rule 12): `source_kind` null; `source_report_id` → `small_group_reports.id` **ON DELETE SET
  NULL**; `source_member_id` / `source_guest_id` (the attendance row's person); `source_section`
  (`prayer` | `praise` | `followUp`, with `source_report_id`; there is no item id: a report edit rewrites
  every item); `source_conversation_id` → `report_conversations.id` ON DELETE SET NULL. CHECK: the
  columns match `source_kind` (attendance: report + one person; section: a section; conversation:
  conversation; none: all null). After a delete the kind stays and the ids go null: the API reports the
  source as gone.
- `cancel_reason` (≤ 500, null), `completed_at` (timestamptz, null).
- `created_at`, `edited_at`, `deleted_at`.
- CHECK `kind IN ('call', 'meeting', 'visit') OR status = 'done'` (rule 6).
- Indexes: `(occurred_on DESC)`, `(author_user_id, status, occurred_on)` for Coming up, and partial
  on `deleted_at IS NULL` where it helps.

**`care_log_entry_people`:** `entry_id` → entries ON DELETE CASCADE, person pair (CHECK exactly one),
unique `(entry_id, member_id)` and `(entry_id, guest_id)`; indexes on `member_id` and `guest_id` for
the timeline.

**`care_log_entry_participants`:** `entry_id` ON DELETE CASCADE, `member_id` → `members.id`, unique
pair. Members only (staff who took part).

**`care_log_entry_revisions`:** `entry_id`, `text`, `created_at`. Never returned by the API.

**Seed** (`data/seed/care.py`, registered in `runner.SEEDERS`): the canvas story, so staff-app and
the boards line up. Lucía Fernández (Jóvenes Bello Horizonte): a call by an elder on Sep 26 from the
Sep 24 follow-up item, WhatsApp messages by her group's leader, a past planned call still waiting for
*Record how it went*, a planned in-person meeting ahead with a leader as participant, and an *Elders
only* `heard` entry. A guest with a visit from a follow-up item. Dates relative to the seed's
"today", like the other seeders.

## Stage 2: care log routes, people search, visibility

New router `api/routers/care_log.py`, mounted at `/care-log`.

**Who sees an entry** (rule 8): one function, `care_log_visible(claims, member, scopes, entry)`, and
its SQL twin `care_log_visible_condition(...)` for lists and the timeline. Both give the same answer:
- `careLog: all` → yes;
- the author (`author_user_id = sub`) → yes;
- `visibility = leaders` and `careLog: view` and **at least one of its people** is in the caller's
  members / guests scope (`MemberScope` / `GuestScope` in `api/access.py`, used as they are) → yes;
- otherwise no. Outside it, every route is **404**. The person never sees anything (no member access
  exists).

**Routes:**

| Route | Permission | What |
| --- | --- | --- |
| `GET /care-log/people-search?q=` | `careLog: create` | Members and guests the caller may log about (`MemberScope` / `GuestScope`; inactive members never), at most 10, the tag search's shape and ranking |
| `POST /care-log` | `careLog: create` | Create (body below) |
| `GET /care-log/{id}` | `careLog: view` | One entry, if visible |
| `PATCH /care-log/{id}` | author only | Edit fields; text changes write a revision and set `edited_at` |
| `DELETE /care-log/{id}` | author only | Soft delete (`deleted_at`) |
| `POST /care-log/{id}/complete` | author or participant | `{ text, occurredOn? }`: planned → done; date defaults to the planned one, never in the future |
| `POST /care-log/{id}/cancel` | author or participant | `{ reason? }`: planned → cancelled |

**Body** (`POST`; `PATCH` takes the same fields, all optional):

```jsonc
{
  "kind": "meeting", "status": "planned",           // status: done | planned
  "meetingMode": "inPerson",                        // meeting only
  "occurredOn": "2026-10-18", "occurredAtTime": "12:30",
  "people": [{ "memberId": 41 }, { "guestId": 7 }], // 1–10
  "others": "her younger brother, 15",              // optional, ≤ 200
  "participants": [12],                             // member ids, optional, ≤ 10
  "heardFrom": "her mother, after the service",     // heard only
  "text": "…",                                      // 1–4000 after trimming; optional when planned
  "visibility": "leaders",                          // leaders | private
  "source": { "kind": "conversation", "conversationId": 88 } // optional
}
```

**Validation** (422 with a `code` staff-app tells apart):
- `kind_status`: `planned` for message, heard or note; `cancelled` in a create.
- `date`: a `done` entry in the future; a `planned` one in the past on create (an existing plan can
  pass its date, that's *Record how it went*).
- `text`: empty for `done`, longer than 4000; `others` / `heardFrom` over 200; `heardFrom` on another
  kind; `meetingMode` on another kind or missing on a meeting.
- `people`: none, more than 10, an inactive member, or anyone outside the caller's scope without
  `careLog: all` (**404** for a person outside the scope, like other scoped lookups).
- `source`: the caller must be able to see it (attendance, the `followUp` section and threads: the
  observation audience, `conversation_access`; the `prayer` and `praise` sections: anyone who can see the
  report's group). Otherwise 404.

**Errors:** 409 `link` when the caller has no linked member (as conversations rule 5): *"Link your
account to a member to log care."* 403 without the permission; 403 `author` for edit, delete,
complete or cancel by someone else.

**Response** (`CareLogEntrySchema`, also used inside timelines and cares):

```jsonc
{
  "id": 301, "kind": "meeting", "status": "planned", "meetingMode": "inPerson",
  "occurredOn": "2026-10-18", "occurredAtTime": "12:30",
  "people": [{ "memberId": 41, "guestId": null, "name": "Lucía Fernández", "viewable": true }],
  "others": null, "participants": [{ "memberId": 12, "name": "Andrea Gutiérrez" }],
  "heardFrom": null, "text": "…", "visibility": "leaders",
  "author": { "memberId": 3, "name": "Roberto Aguilar" },
  "source": { "kind": "conversation", "reportId": 120, "meetingDate": "2026-09-24",
              "smallGroup": { "id": 4, "name": "Jóvenes Bello Horizonte" }, "visible": true, "gone": false },
  "pastDue": false,     // planned and occurred_on < church today
  "canEdit": true, "canComplete": true,
  "editedAt": null, "createdAt": "…"
}
```

`viewable` per person follows tags rule 12 (`viewable_people`). `source.visible` is false when the
caller can't open it (staff-app shows "A report note you don't have access to"); `gone` is true when
the source was deleted.

**Try:** every role above; a leader logging about someone in another leader's group (404); a leader
seeing an entry shared with the leaders of one of its people but not the private one; an elder seeing
both; the author always seeing their private entry; complete and cancel by a participant; an
attendance source whose report is deleted (`gone`).

## Stage 3: `careLog` timeline source

In `data/small_groups/timeline_services.py` (or move the sources to `data/timeline/` now that there
are three: your call, note it), add a source per inactive-guests rule 15:
- Entries **about** the person (`care_log_entry_people`), visible to the caller
  (`care_log_visible_condition`), not deleted, not cancelled.
- In the date range like reports, **except planned entries still ahead** (`occurred_on > today`):
  they're always included, so staff-app can show *Coming up* (rule 11).
- They have no group: left out when a group is picked, like status entries.
- Kind `careLog`, carrying `CareLogEntrySchema`. Ties on one date: status, then care log, then
  report (newest recorded first within a kind).
- `earliestDate` and `latest` count them.
- `counts` gains `careLog`: entries in the range (ahead-planned ones included). The report counts
  don't change (rule 13).

**Try:** dump the timeline before and after for every role × seeded person × the usual parameter
sets; everything but the new entries and `counts.careLog` byte-identical.

## Stage 4: Coming up

`GET /care-log/coming-up` (`careLog: view`): the caller's planned entries (author **or** participant),
not deleted:
- `pastDue`: `occurred_on < church today`, oldest first;
- `upcoming`: today through today + 7, soonest first.

Shape: `{ "pastDue": [CareLogEntrySchema], "upcoming": [CareLogEntrySchema] }`. No paging: only the
caller's own plans (rule 11). Empty lists when there are none.

## Stage 5: docs (Part 1)

- `docs/ARCHITECTURE.md`: a *Care log* section (the domain, visibility, sources, the timeline
  source) and the new routes in the role × route table.
- `CLAUDE.md`: one bullet pointing at it, in the style of the others.
- Mark Part 1 done in this log.

---

# Part 2: care (branch `feature/care`)

## Stage 6: migration, models, seed

**Enums:** `CareStatus` (`open`, `monitoring`, `closed`), `CareVisibility` (`private`,
`peoples_leaders`, `all_leaders`), `CareEventKind` (`started`, `status`, `urgent`, `owners`,
`visibility`, `people`, `prayer`, `linked`, `unlinked`, `reopened`, `closed`, `entry_moved`).

**`care_cases`:** `title` (≤ 120), `description` (≤ 4000), `others` (≤ 200, null), `status`,
`urgent` (bool), `visibility`, `next_check_in_on` (date, null; CHECK null exactly when closed),
`prayer_summary` (≤ 280, null), `prayer_summary_by_member_id` (null), `prayer_summary_at` (null),
`started_by_user_id`, `started_by_member_id`, `created_at`, `last_activity_at` (never moved back,
like conversations rule 17), `closed_at`, `closed_by_user_id`, `closing_note` (CHECK: set exactly
when closed).

**`care_case_people`** (person pair, unique), **`care_case_owners`** (`member_id`, `user_id`,
`added_by_user_id`, `added_at`; unique `(care_case_id, member_id)`), **`care_case_events`**
(`kind`, `data` jsonb, `by_user_id`, `by_member_id` null, `created_at`), **`care_case_links`**
(`source_kind` attendance | section | conversation, the same source columns as entries with ON DELETE
SET NULL, `created_by_user_id`, `created_at`), **`care_case_reads`** (`user_id`, `last_read_at`,
unique), **`care_case_revisions`** (`field`, `value`, `by_user_id`, `created_at`; never returned).
All child tables cascade from `care_cases`.

**`care_log_entries`** gains `care_case_id` → `care_cases.id` (null; ON DELETE RESTRICT: cares are
closed, never deleted), and `visibility` becomes nullable with CHECK
`(care_case_id IS NULL) = (visibility IS NOT NULL)` (rule 9).

**Seed:** the canvas cares, so the boards and the API agree: *Support for Marisol and her daughter*
(urgent, overdue, `private`, an elder and her group's leader as owners, prayer summary), *Lucía
stepping back as co-leader* (due today, `peoples_leaders`, an elder and Andrea as owners, Lucía's
Part 1 entries moved in), *Carmen's mother in the hospital* (no owner, started by a leader), *José's
job search* (`all_leaders`, a leader owner, prayer summary), *Rojas family* (monitoring), *Teresa's
surgery* (closed with a note).

## Stage 7: access, create, read, edit, status, owners, read marks

**The access function** (rule 18), in `api/access.py` or `data/care/access.py`, with its SQL twin;
**every** route, list, count and timeline source uses it:
- `care: all` → can open, and acts as an owner (manage).
- Otherwise needs `care: view` and one of: an owner (`care_case_owners.user_id = sub`);
  `peoples_leaders` with a person in the caller's members / guests scope; `all_leaders`.
- Outside it: **404**, and the care appears nowhere (rule 19).
- **Manage** = owner or `care: all` (status, check-in, owners, visibility, edit, prayer summary).

**Routes** (router `api/routers/care_cases.py`, `/care-cases`):

| Route | Who | What |
| --- | --- | --- |
| `POST /care-cases` | `care: create`, linked member, people in scope | Create: title, description, people, others, visibility (**required, no default**: 422 `visibility`), owners (member ids; the caller may be one), urgent, nextCheckInOn, prayerSummary, source (optional, as for entries; an entry source is `{ "kind": "careLogEntry", "entryId" }`, which **moves** the entry in, author or `careLog: all` only). Writes a `started` event. Owners must be linked members whose users have `care: view` (stage 11 checks it; until then, linked members) |
| `GET /care-cases/{id}` | can open | The care, its people, owners, links and the **stream** (entries inside it, not deleted, and events), newest first, plus `lastReadAt` and `canManage` / `canUpdate` / `canTake` |
| `PATCH /care-cases/{id}` | manage | title, description, people, others, visibility, urgent, prayerSummary. Each change writes an event (people, visibility, urgent, prayer) and a revision for text fields. Narrowing visibility so that an owner could no longer open it isn't possible (owners always can) |
| `POST /care-cases/{id}/status` | manage | `{ status: open | monitoring }` with `nextCheckInOn` when reopening; `{ status: closed, closingNote }` (closing note required, 422 `closing_note`). Events `status` / `closed` / `reopened` |
| `POST /care-cases/{id}/take` | `care: update`, can open, no owners | The caller becomes the owner (409 `has_owner` if someone took it first) |
| `POST /care-cases/{id}/owners` | manage | `{ memberId }` |
| `DELETE /care-cases/{id}/owners/{memberId}` | manage | Removing the last owner makes it *Needs an owner* again |
| `POST /care-cases/{id}/read` | can open | `last_read_at = greatest(existing, last_activity_at)` |

**Rules to enforce:**
- `nextCheckInOn` is required while open or monitoring, never in the past (422 `check_in`), null when
  closed. It changes **only** through an update (stage 8) or reopening (rule 23): `PATCH` doesn't
  take it.
- Every write bumps `last_activity_at` (entries and events), never moves it back.
- Commenting-style rule: every write needs a linked member (409 `link`).
- Closed cares are readable and still take entries (rule 31), but not status changes other than
  reopening.

## Stage 8: entries inside a care, check-ins, links, moving entries in

- `POST /care-log` accepts `careCaseId` (caller must be able to open it and have `care: update`).
  Inside a care: no `visibility` (422 if sent), people optional and must be the care's people.
- **Check-in with the update** (rule 23): the body may carry `nextCheckInOn`, accepted only from a
  manager (403 `owner` otherwise); it sets the care's date and the response says so. Without it, the
  date doesn't move.
- **Suggested check-in:** urgent 3 days, open 14, monitoring 30 (constants in v1). Return them in
  `GET /care-cases/{id}` as `checkInSuggestionDays: { urgent, open, monitoring }`, so staff-app
  pre-fills the date without its own copy of the numbers.
- **Links** (rules 35–36): `POST /care-cases/{id}/links` `{ source }` links a report row, item or
  thread (the caller must see it); `{ kind: "careLogEntry", entryId }` moves an entry in (author or
  `careLog: all`; its `visibility` becomes null, event `entry_moved`). `DELETE
  /care-cases/{id}/links/{linkId}` (manage). A deleted source leaves the link with null ids and an
  `unlinked` event written by the delete path (report delete, conversation delete) in the same
  transaction.
- **Moving changes who sees the entry:** return `visibilityBefore` / `visibilityAfter` labels from a
  `GET /care-cases/{id}/move-preview?entryId=` so staff-app can show the warning (rule 34) without
  copying the rule.

## Stage 9: care lists, counts, prayer summaries

`GET /care-cases?tab=attention|open|unread|closed&mine=&urgent=&groupId=&page=` (`care: view`), only
cares the caller can open:
- **attention** (rule 39): cares with no owner; the caller's own cares that are overdue, due today
  or urgent; with `care: all`, everyone's overdue, due and urgent cares. Order: urgent first, then
  overdue, due, later; ownerless ahead on the same rank; then `last_activity_at` desc.
- **open**: open and monitoring. **closed**: closed, newest closed first.
- **unread**: new or updated since the caller's read mark by someone else, any status (filtered in
  SQL against `care_case_reads`, like the conversations *Unread* tab).
- `mine`: the caller is an owner. `groupId`: a person on the care is active in that group.
- Row shape: id, title, status, urgent, visibility, people (names, groups), owners, nextCheckInOn
  with `checkIn: overdue | due | later | none`, latest stream item preview (who + text, clamped),
  `unread`.

`GET /care-cases/counts` → `{ attention, open, unread, prayer, closed, badge }` where `badge` is the
sidebar's (rule 39): own cares overdue or due, plus, with `care: all`, cares with no owner. A
leader's badge never counts other people's cares.

`GET /care-cases/prayer-summaries` (`care: view`): every care with a prayer summary, **whatever the
caller can open** (rule 32): `{ text, sharedBy, sharedAt, careCase: { id, title } | null }`, the
`careCase` only when the caller can open it. Open and monitoring cares only; newest first.

## Stage 10: `care` timeline source and linked-care lookups

- **Timeline** (rule 38): a source of kind `care` with *Care started* (on `created_at`'s church date)
  and *Care closed* entries for each care about the person that the caller can open, carrying
  `{ id, title, status, visibility, owners }`. They get their own `counts.care`; staff-app's *Care*
  chip adds `counts.careLog` and `counts.care`.
- Care log entries inside a care carry `careCase: { id, title }` in `CareLogEntrySchema` (the caller
  can always open it, since the entry's visibility is the care's).
- **Linked-care lookups** (rule 37): `GET /care-cases/linked?reportIds=1,2,3` returns, per report,
  the links to cares the caller can open: `[{ reportId, anchor: { type: attendance, memberId |
  guestId } | { type: item, itemId } | { type: conversation, conversationId }, careCase: { id, title
  } }]`. Used by Report detail, the conversation panel and Prayer & follow-up. Nothing for cares the
  caller can't open.

## Stage 11: owner options

`GET /care-cases/owner-options?q=` (`care: view`): linked members whose users have `care: view`,
for the owner picker (rule 27):
- Calls auth-server `GET /internal/users/with-permission?permission=care:view` (shared internal
  token, the client Part 2 of report conversations added), joins `members.user_id`, filters by `q`,
  at most 10.
- Cache the auth-server answer briefly (a minute) per process; on failure return 503 with a code so
  staff-app can say the list couldn't load.
- Use the same check when adding an owner (stage 7) and when creating with owners: 422 `owner` for a
  member whose user lacks `care: view`.
- For `private` and `peoples_leaders` cares, adding an owner is what gives them access; the response
  of `POST …/owners` says so (`grantsAccess: true`).

## Stage 12: docs (Part 2)

- `docs/ARCHITECTURE.md`: a *Care* section (access function, manage, stream and events, check-ins,
  links and moves, lists and counts, prayer summaries) and the routes in the role × route table.
- `CLAUDE.md`: one bullet.
- Mark Part 2 done in this log.

## For the other repos

- staff-app regenerates nothing (types are hand-written there); its handoff mirrors the schemas
  above. Tell it about any field you rename.
- auth-server: nothing beyond its two stages and the existing internal endpoint.
- Not in this handoff: email (rule 41, a later Part 3 on the report conversations outbox).
