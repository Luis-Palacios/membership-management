# Prayer & follow-up: the week's shared texts and section threads

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
| 1. Shared texts endpoint | ⬜ | |
| 2. Section threads: migration, models, anchor union | ⬜ | |
| 3. Section threads: routes, summaries, inbox | ⬜ | |
| 4. Conversations on shared entries, seed | ⬜ | |
| 5. Docs | ⬜ | |

### Decisions and deviations

- (fill in per stage)

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

ConversationAnchorSchema = Annotated[AttendanceAnchorSchema | SectionAnchorSchema, Field(discriminator="type")]
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
