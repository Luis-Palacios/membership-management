# Prayer & follow-up: the week's shared texts and section threads

> **Report tags:** the report's `groupPrayerRequest`, `groupPraiseReport` and `groupRelevantDiscussion` text fields below no longer exist. They became items (`sections`), see `docs/REPORT-TAGS-API-HANDOFF.md`. Everything else here still holds.

Handoff spec for the membership-management side of **Prayer & follow-up**. Read the cross-repo
spec first: `../docs/specs/prayer-follow-up.md` (workspace folder `members-management/docs/specs/`);
its rules are referred to as *rule N*. It builds on `docs/GROUPS-DASHBOARD-API-HANDOFF.md` (the week
endpoint and its status logic) and `docs/REPORT-CONVERSATIONS-API-HANDOFF.md` (Part 1, on `main`),
whose rules are *conversations rule N*.

Two pieces of work:

- **Stage 1: `GET /small-group-reports/shared`**, the week's prayer, praise and follow-up texts plus
  the groups still to report. No migration.
- **Stages 2–4: section threads.** A conversation can be about a report section (`prayer`,
  `praise`, `followUp`) instead of a person (rule 14, which lifts conversations rule 2). One
  migration.

> **Email stays out.** Report conversations Part 2 (`docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`)
> is still pending and comes **after** this, worked slowly as a learning exercise. Don't add outbox
> rows, recipients or auth-server calls here, and don't start Part 2's stages. The spec's
> *Changes for report conversations Part 2* lists what section threads change there, and that
> handoff already has a note at the top pointing to it.

Work through it **stage by stage**, one reviewable commit per stage, on the **`prayer-follow-up`**
branch (the same name in every repo). Each stage must pass `uv run ruff check .` and
`uv run ty check` (and `uv run alembic check` in stage 2), and be tried against the local API
(`TestClient` with the claims dependency overridden, as before) as each role: `admin`, `elder`
(linked and unlinked), `smallGroupLeader` (in and out of scope, former leader), `deacon` with no
member, `user`. There's no test runner yet, so note in *Decisions and deviations* what you tried
and how.

Keep the existing conventions: routes call `services.py` / `conversation_services.py` directly,
`queries.py` builds `Select`s, `results.py` holds `NamedTuple`s mapped with `all_as`, schemas are
`CamelModel`, service errors are domain exceptions the router maps to HTTP codes, "today" is
`church_today()`, and routes doing blocking database work stay plain `def`.

## Progress (handoff log)

| Stage | Status | Commit |
| --- | --- | --- |
| 1. Shared texts endpoint | ✅ | `93a7ae4` |
| 2. Section threads: migration, models, anchor union | ✅ | `90af585` |
| 3. Section threads: routes, summaries, inbox | ✅ | `995ea4a` |
| 4. Conversations on shared entries, seed | ✅ | `64ccdf2` |
| 5. Docs | ✅ | this commit |

### Decisions and deviations

- **How it was tried:** no test runner, so throwaway `TestClient` scripts (not committed) with
  `get_current_claims` overridden per role, against a scratch Postgres database (`pfu-scratch`,
  migrated and seeded, plus fixture rows; today = 2026-10-22). The dev database was not touched.
- **Stage 1:** `get_report_week` is split into `_week_bounds` (week, `FutureWeekError`),
  `_open_report_groups`, `_active_leaders_by_group` and `_week_groups` (per-group status over any set
  of groups); `get_report_shared` reuses all four on the scoped open groups. `week_reports_query` now
  takes the group ids and filters in SQL (it filtered in Python before). The week endpoint's body was
  compared with `main` for five dates (current, three past, one future): identical. Entries come
  from a new `shared_reports_query` (held only, ordered meeting date, group name, report id); texts
  are trimmed in the service. A report with all three texts empty is kept, as the handoff says.
  `stillToReport` is `StillToReport` (status narrowed to `notFiled`/`today`/`upcoming`, date never
  null). `conversations` is already typed with its stage 4 shape (`SharedConversationSchema`, keys
  `prayer`/`praise`/`followUp`) so the staff app's generated types don't change later; it's `{}`.
  Tried: admin, elder linked and unlinked see every open group; a no-meeting report and a closed
  group's held report never appear; blank and spaces-only text is `null`, line breaks kept; a Sunday
  and a Saturday report of one group land in the same week; any day of a week gives the same body;
  `notHeld`, `submitted`, `noLeader` and `noMeetingDay` groups aren't listed, the rest order
  `notFiled`, `today`, `upcoming`, then name; leader of one group sees only that group (entries and
  still to report); former leader (only a closed group) and deacon with no member get empty lists;
  `user` 403; next week 422 `The week can't be in the future.`
- **Stage 2:** migration `a0bb7197cbc8`. Autogenerate found only the column and the nullable
  `member_id`; the two checks (`ck_report_conversations_section_valid`, `..._one_anchor`) and the
  unique constraint are hand-written. The unique constraint is **named explicitly**
  (`uq_report_conversations_report_id_section`): the `uq` naming convention uses only the first
  column, so it would have clashed with the existing `uq_report_conversations_report_id` (which is
  also why autogenerate didn't see it). The downgrade fails if section threads exist (they can't
  be expressed without `section`); delete them first. `ReportSection` (`StrEnum`) lives next to the
  model with `report_attribute` mapping each key to its `SmallGroupReport` attribute; the column is
  VARCHAR + CHECK like `role` and `sex`, so a new section needs a hand-written migration. Beyond the
  handoff: the thread response's `member` is nullable too (a section thread has none), inbox rows
  already carry `anchor` (the contract says they do; harmless before stage 3), and the shared
  entry's `conversations` keys are typed `ReportSection`. Tried: `alembic check` clean, downgrade
  -1 and upgrade round-trip on the scratch DB; inserts with both anchors, no anchor, an unknown
  section and a duplicate section each fail on the right constraint. Summaries, every person thread
  (incl. 404 no thread, 422 not on the report), counts and all three inbox tabs with and without a
  group filter were dumped for admin, elder linked and unlinked, two leaders, former leader, deacon
  with no member and `user` on this branch and on `main`: identical once the inbox `anchor` is
  removed, and every inbox `anchor` is `attendance` with the row's member. A hand-inserted prayer
  thread (deleted afterwards) shows in the summary with a section anchor, in the inbox with `member:
  null`, and counts toward *needs my reply* for the leader, not the elder who wrote it.
- **Stage 3:** one anchor type, `ConversationAnchor = int | ReportSection` (a member id or a
  section), threads through `get_report_anchor_conversation` (was `get_report_member_conversation`),
  `add_comment` and `_get_or_create`; `_check_can_start` is the only branch (attendance row for a
  person, trimmed text for a section, via `section_text_query`). The router's person and section
  routes share `_anchor_thread` / `_add_anchor_comment`; the section comment route uses the same
  rate-limit scope as the person one, so they share one budget. **Unknown key:** FastAPI's enum error
  doesn't mention the section, so `key` is a `str` checked by `_section_or_422` (422 `Unknown section
  'notes'.`); the OpenAPI schema still lists the three values (`json_schema_extra` enum). Inbox,
  counts and summaries needed no change (they're per thread). Report delete: `conversationCount`
  already counted every thread of the report, and the database cascade removes section threads and
  their comments. Tried on the scratch DB: elder starts a prayer thread (201, `member: null`, comment
  trimmed); it shows in the leader's summary and *Needs my reply* inbox with a section anchor, and
  counts go up for the leader; the leader's reply flips it to the elder's side; resolve, reopen, and
  a comment on a resolved thread reopens it; mark read and edit own work by id, editing someone
  else's 403; empty praise (null), spaces-only praise and a no-meeting report 422 `This section is
  empty.`; unknown key 422 on GET and POST; GET with no thread 404 `No conversation yet.`; a leader
  out of scope, former leader and deacon with no member 404; `user` 403; unlinked elder reads (200)
  and gets 409 on comment; a leader starts a follow-up thread; person threads unchanged; clearing
  the prayer text keeps the thread readable and repliable; report detail counted 3 threads, and
  deleting the report left no threads or comments (the thread id is then 404).
- **Stage 4:** the summaries query is split into `_conversation_summaries_query` (now also selecting
  `report_id`), filtered by one report (`report_conversation_summaries_query`, unchanged output) or
  by several reports' section threads (`section_conversation_summaries_query`); both services build
  rows with one `_summary`. The shared route calls `get_section_conversations` once for every
  entry, limited to `conversation_group_ids` (the conversations' audience): for today's roles that's
  the whole scope, but a full role without `viewObservations` gets `{}` everywhere instead of
  threads it couldn't open. Seed: `SeedThread.section`; a section thread takes the first held report
  from `report` back that has text in that section. Three threads: `followUp` on GP-#2's newest
  report (elder, then leader: waiting for the elders), `prayer` on GP-#1's newest (resolved by an
  elder), `praise` with one elder comment on GP-#4's newest (waiting for the leaders); two
  `--reset` runs gave identical rows. Tried on the reseeded scratch DB: one conversations query per
  request (none when no report is in the audience); the elder and the group's leader see opposite
  `needsMyReply` on the follow-up and praise threads; unlinked elder same as linked; a leader sees
  only their groups' threads; former leader, deacon with no member: no entries; `user` 403; a week
  with no threads is `{}` on every entry; a read clears `unread` for the reader only; a leader's
  reply raises `commentCount` and flips both sides, deleting it puts both back (deleted comments
  aren't counted); report 14's summary agrees with its shared entry. Summaries, threads, counts and
  the inbox for every role are identical to stage 3 on the same data.
- **Seed quirk (pre-existing, fixed after stage 5):** the seed's default `today` was the UTC date,
  so run on a Managua evening it was already tomorrow and the newest reports' times, capped at
  "today 08:00", landed hours in the future (such a thread stayed `unread` after a read). The default
  is now Managua's date; `MANAGUA_TZ` moved to `data/seed/context.py` and is shared by the runner and
  both seeders that used it. Checked on a Managua evening (UTC already the next day): no report,
  comment or thread time after `now()`; with `--today` pinned the rows are identical to before.
- **Stage 5:** `README.md` has no route list (the role × route table is in `docs/ARCHITECTURE.md`),
  so the new routes went there: the table, a *Prayer & follow-up* entry under small group reports
  and an *Anchor* entry under *Report conversations*. `CLAUDE.md`'s conversations line names section
  threads, and `docs/REPORT-CONVERSATIONS-API-HANDOFF.md` has the pointer under its title.

## Who can do what

| Role | `GET …/shared` | Section threads |
| --- | --- | --- |
| admin, elder | every open group | read, start, reply (start/reply need a linked member, conversations rule 5) |
| smallGroupLeader, deacon (leading) | groups in scope | same, on reports in scope |
| former leader, deacon with no member | empty `entries` and `stillToReport` | 404 on reports out of scope |
| user | 403 (`smallGroupReports: view`) | 403 |

Leaders and deacons reach the page too (rule 2), so the scoping matters: try it for every role.

## Stage 1: Shared texts endpoint

**Route:** `GET /small-group-reports/shared?date=` in `api/routers/small_group_reports.py`,
declared **before** `/small-group-reports/{report_id}` (same reason as `summary` and `week`).
Dependency `require_permission("smallGroupReports", "view")` and the `SmallGroupScopeDep`.

**Week:** reuse the week endpoint's date handling: `date` optional (default `church_today()`),
`[church_sunday(d), church_sunday(d) + 6]`, 422 with `future` in `detail` for a week after the
current one.

**Entries** (rules 6–8): held reports (`held = true`) with `meeting_date` in the week, for groups
**open today** and in scope. Select only what's needed: report id, meeting date, group id/name and
the three texts. Trim each text and map blank to `null` in the service, not the query. Order:
`meeting_date`, then group name, then report id. A report whose three texts are all empty is still
returned (the client simply lists it nowhere); say in the log if you'd rather drop it.

**Leaders:** the group's leaders **active today**, leader first, then co-leaders by name, exactly as
`get_report_week` builds them. Factor that into one helper both use rather than copying it.

**`stillToReport`** (rule 11): the open groups in scope whose week status is `notFiled`, `today` or
`upcoming`, with `meetingDate` (= D). Don't duplicate the status logic: `get_report_week`
(`data/small_groups/services.py`) computes it for every open group; split out the per-group status
computation so it can run on the scoped set of groups, and call it from both. `submitted`,
`noLeader` and `noMeetingDay` groups are not listed. Order as the week view (`notFiled`, `today`,
`upcoming`, then name).

**`conversations`:** return `{}` on every entry in this stage. Stage 4 fills it.

**Shape:** as in the spec's *Contracts*. Schemas `ReportSharedSchema`, `ReportSharedEntrySchema`,
`ReportStillToReportSchema` next to the week schemas.

**Try:** admin and elder see every open group's held reports in the week; a no-meeting report never
appears; a closed group's report never appears, even in a past week; a leader sees only their
groups; former leader and memberless deacon get empty lists; `user` 403; `date` in a future week
422; a Sunday and a Saturday report both land in the same week; blank text (spaces only) is `null`.

## Stage 2: Section threads: migration, models, anchor union

**Migration** on `report_conversations` (`uv run alembic revision --autogenerate`, then review):

- `member_id` becomes **nullable**.
- New `section` column, `String(16)`, nullable, with a check constraint
  `section IN ('prayer', 'praise', 'followUp')`.
- Check constraint: exactly one anchor, `(member_id IS NULL) <> (section IS NULL)`.
- New unique constraint `(report_id, section)`. Keep the existing `(report_id, member_id)` one:
  Postgres treats NULLs as distinct, so section threads don't collide with it.

No data migration: every existing row has a `member_id`. `alembic check` clean afterwards.

**Model:** `ReportConversation.member_id: Mapped[int | None]`, new `section: Mapped[str | None]`.
A small `ReportSection` `StrEnum` (`prayer`, `praise`, `followUp`) with the mapping to the report
column (`group_prayer_request`, `group_praise_report`, `group_relevant_discussion`), in one place.

**Anchor union** (`api/schemas/report_conversations.py`): replace the single `ConversationAnchorSchema`
with a discriminated union on `type`:

```python
class AttendanceAnchorSchema(CamelModel):
    type: Literal["attendance"] = "attendance"
    member_id: int


class SectionAnchorSchema(CamelModel):
    type: Literal["section"] = "section"
    key: ReportSection


ConversationAnchorSchema = Annotated[
    AttendanceAnchorSchema | SectionAnchorSchema, Field(discriminator="type")
]
```

Fix every place that builds an anchor from `member_id` (`_thread_schema`, the summaries) so it
builds the right variant. Every query that joins `members` on `report_conversations.member_id` (the
inbox above all) must become an **outer** join; `member` in inbox rows becomes nullable. After this
stage nothing can create a section thread yet, so behaviour is unchanged: try the existing person
thread routes and the inbox for every role and compare with `main`.

## Stage 3: Section threads: routes, summaries, inbox

**Routes** in `api/routers/report_conversations.py`, declared **before** the `{member_id}` ones
(`sections` isn't an int, but be explicit):

| Route | Behaviour |
| --- | --- |
| `GET /small-group-reports/{id}/conversations/sections/{key}` | As `GET …/conversations/{memberId}`: 404 `No conversation yet.` when none |
| `POST /small-group-reports/{id}/conversations/sections/{key}/comments` | As the person route: creates the thread if needed, reopens if resolved, same rate limit, same 409 for an unlinked member |

- Unknown `key` → 422 with `section` in `detail` (let FastAPI's enum validation do it if its
  message contains the word; otherwise map it).
- **Starting** a thread on a section whose text is empty (null or blank) → 422
  `This section is empty.` (rule 14). **Replying** to an existing section thread is allowed even if
  the text has since been cleared.
- No-meeting reports have no sections: 422 `This section is empty.` covers them.
- Share the access helper and the comment service with the person routes: add an anchor parameter
  to `add_comment` / the thread lookup rather than duplicating them. `edit`, `delete`, `resolve`,
  `reopen` and `read` work by id and need no change.

**Summaries** (`GET /small-group-reports/{id}/conversations`): include section threads. Each item
already carries `anchor`; the staff app switches to reading it in its stage 2.

**Inbox and counts:** section threads count toward every tab and `needsMyReply` exactly like person
threads; rows carry the anchor and `member: null`. Group filter and ordering unchanged.

**Report delete:** the conversation count in the delete dialog includes section threads (it should
already, via the cascade query; confirm).

**Try:** start a prayer thread as an elder → it appears in the summary, the leader's inbox under
*Needs my reply*, the counts; reply as the leader → flips to the elder's side; resolve/reopen;
start on an empty praise → 422; start on a no-meeting report → 422; unknown key → 422; a leader out
of scope → 404; an unlinked elder can read but gets 409 on comment; delete the report → the thread
is gone.

## Stage 4: Conversations on shared entries, seed

**`conversations` on each shared entry:** for the week's report ids, the section threads only, keyed
by section: `id`, `status`, `commentCount` (non-deleted), `unread`, `needsMyReply`, computed for the
caller as the per-report summaries do. One query for all entries (batch by report ids), not one per
entry. A key is absent when that section has no thread.

**Seed** (`data/seed/small_group_report_conversations.py`): add a few section threads on recent
reports: an elder-started `followUp` thread with a leader reply (needs the elder's reply), a
resolved `prayer` thread, one `praise` thread with a single comment. Keep it deterministic like the
rest of the seed.

**Try:** the shared endpoint shows the right counts and flags per caller (elder vs the group's
leader see opposite `needsMyReply`); weeks with no threads return `{}` everywhere.

## Stage 5: Docs

- `README.md` / route list: the new routes.
- `docs/REPORT-CONVERSATIONS-API-HANDOFF.md`: one line under its title saying section threads were
  added by this handoff.
- Tick the progress log.

## Not in this spec

- Email of any kind (report conversations Part 2).
- Marking entries handled, multi-week ranges, exports.
- A weekly view of observations (they stay on Report detail only).
