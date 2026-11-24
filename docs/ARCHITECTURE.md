# Architecture (target / vision)

This describes where the project is headed, not what's built yet — for current implementation state, see the root `CLAUDE.md`.

## System shape

A single microservice — membership management (assimilation): membership applications, members, small groups and small-group reports — augmenting an existing church web application (SQL Server DB, real users) by adding a new component alongside it rather than extending it directly.

- Uses the **existing SQL Server DB** via SQLAlchemy (this is the code that exists today, under `src/membership_management/data/assimilation/`).
- FastAPI surface to list, review, and approve membership applications.
- Planned areas beyond applications: members management, small groups, and small-group reports.

## Permissions (built)

Rules: `docs/specs/roles-and-permissions.md` (workspace repo); this side:
`docs/ROLES-PERMISSIONS-API-HANDOFF.md`. **No role names are checked here.** auth-server's
`statements.ts` is the only role → permission map; it puts the caller's permissions in the JWT as
`perms` (`Record<resource, action[]>`), and every route checks those:

- `api/jwt_auth.py`: `AuthClaims.perms` (missing → `{}`, fail closed), `has_permission(claims,
  resource, action)` and `require_permission(resource, *actions)` (all-of, 403).
- **Permissions say what, scope says on which records** (`api/access.py`). `SmallGroupScopeDep`:
  403 without `smallGroups: view`; with `smallGroups: all` every group, otherwise the groups the
  caller's member leads or co-led when they closed. `MemberScopeDep`: with `members: all` every
  member, otherwise members active in an open group of that small group scope. Out of scope is 404
  (same message as missing); a missing permission is 403.
- Leadership rule 9: adding, promoting to or changing a `leader` row needs `smallGroups:
  setLeader`; without `smallGroups: all` you can't change your own row. Report observations need
  `smallGroupReports: viewObservations`, or leading the report's group. A member's `email` can be changed
  with `members: all`, or without it while the member has no `user_id`. `PATCH /me/member` needs `ownProfile: update` and ignores the members scope:
  it only ever touches the member linked to the JWT `sub` (404 if none), and has no `email` field.
- Not permission-gated: `GET /me` (any valid JWT, `pending` included), `GET /health`,
  `GET /health/live`, `/internal/*` (shared `X-Internal-Token`).

What each role gets today (from auth-server's statements; ✓ all records, *scope* only its
records with 404 elsewhere, — 403). `smallGroupLeader` and `deacon` are the same for now; `user` and
`pending` have no permissions and get 403 on every route below, except `PATCH /me/member`, which `user`
also has (`ownProfile: update`); `pending` has nothing.

| Route | Permission | admin, elder | smallGroupLeader, deacon |
| --- | --- | --- | --- |
| `GET /small-groups`, `GET /small-groups/{id}` | `smallGroups: view` (+ scope) | ✓ | scope |
| `POST /small-groups` | `smallGroups: create` | ✓ | — |
| `PATCH /small-groups/{id}` | `smallGroups: update` + scope | ✓ | scope |
| `POST /small-groups/{id}/close` | `smallGroups: close` + scope | ✓ | — |
| `PUT /small-groups/{id}/leader` | `smallGroups: setLeader` + scope | ✓ | — |
| `POST`, `PATCH`, `DELETE /small-groups/{id}/members[/{memberId}]` | `smallGroups: manageMembers` + scope, rule 9 | ✓ | scope, no leader rows, not own row |
| `POST`, `DELETE /small-groups/{id}/guests[/{guestId}]` | `smallGroups: manageMembers` + scope; `newGuest` also needs `guests: create` (403) and the setting on (409); `reactivate: true` also needs `guests: reactivate` (403); an inactive `guestId` without it is 409 `guest_inactive` | ✓ | scope, new guest needs `guests: create`, reactivate needs `guests: reactivate` |
| `GET /small-group-reports`, `/summary`, `/{id}`, `GET /small-groups/{id}/report-roster` | `smallGroupReports: view` + scope | ✓ (observations) | scope (own observations) |
| `GET /small-groups/{id}/tag-search` | `smallGroupReports: create` or `update` + scope (404 outside; `[]` for a closed group) | ✓ | scope |
| `POST /small-groups/{id}/reports`, `PATCH`, `DELETE /small-group-reports/{id}` | `smallGroupReports: create` / `update` / `delete` + scope | ✓ | scope |
| `GET /small-group-reports/week` | `smallGroups: all` + `smallGroupReports: viewObservations` | ✓ | — |
| `POST /no-meeting-weeks` | `smallGroups: all` + `smallGroupReports: create`, and a linked member (409) | ✓ | — |
| `PATCH` / `DELETE /no-meeting-weeks/{id}` | `smallGroups: all` + `smallGroupReports: update` / `delete` | ✓ | — |
| `GET /small-group-reports/shared` | `smallGroupReports: view` + scope; section threads only in the conversations' audience | ✓ | scope |
| `GET /small-group-reports/{id}/conversations[/{memberId}]`, `…/conversations/guests/{guestId}`, `…/conversations/sections/{key}`, `POST /report-conversations/{id}/read` | `smallGroupReports: view` + scope + the observation audience of that report | ✓ | scope |
| `POST /small-group-reports/{id}/conversations/{memberId}/comments`, `…/conversations/guests/{guestId}/comments`, `…/conversations/sections/{key}/comments`, `PATCH`/`DELETE /report-conversation-comments/{id}`, `POST /report-conversations/{id}/resolve`/`reopen` | same, and a linked member (409); edit and delete only your own comment | ✓ | scope |
| `GET /report-conversations` (inbox) | `smallGroupReports: view`; every group with `smallGroups: all` + `viewObservations`, else the scope | ✓ | scope |
| `GET /report-conversations/counts` | none: `{ needsMyReply: 0, hasUnread: false }` outside the audience | ✓ | scope |
| `GET /members?status=` | `members: view` + `all`; `status` is `active` (default), `inactive` or `all` (422 otherwise); `inactiveReason` only with `setStatus` | ✓ | — |
| `GET /members/options` | `members: search`; active members only | ✓ | ✓ (id and name only) |
| `GET /members/search?q=` | `members: view` + members scope (name match, `q` ≥ 2 chars, ≤ 20 rows); `status` on each row | ✓ | scope (id, name and status only; never an inactive member) |
| `GET /members/{id}` | Own member: none (any role, rule 11). Others: `members: view` + members scope. `inactiveReason` / `inactiveNote` only with `setStatus` | ✓ | own + scope |
| `POST /members` | `members: create` | ✓ | — |
| `PATCH /members/{id}` | `members: update` + members scope; `email` needs `all` unless the member is unlinked | ✓ | scope, no `email` |
| `PUT`, `DELETE /members/{id}/user` | `members: link`; `PUT` is 409 `member_inactive` for an inactive member | ✓ | — |
| `POST /members/{id}/deactivate`, `POST /members/{id}/reactivate` | `members: setStatus` | ✓ | — |
| `GET /members/{id}/status-history` | `members: setStatus` | ✓ | — |
| `GET /members/{id}/timeline` | `members: view` + members scope (404 outside, even for your own member without it); report entries by the visibility rules in *Person timeline*, status entries for all who can open it | ✓ (everything) | scope (own groups' attendance, notes, follow-up; prayer and praise from any group; status entries with reason and note) |
| `GET /guests?status=` | `guests: view` + `all`; `status` is `all` (default), `active` or `inactive`, on `guests.status`; `inactiveReason` only with `guests: deactivate` | ✓ | — |
| `GET /guests/search?q=` | `guests: search`; church-wide, rule 14's fields plus `status` and `inactiveSince`; `[]` unless `guests: all` or leading an open guest group | ✓ | ✓ if it leads an open guest group, else `[]` |
| `GET /guests/{id}`, `PATCH /guests/{id}` | `guests: view` / `update` + guests scope; `inactiveReason`, `inactiveNote`, `statusHistory` only with `guests: deactivate` | ✓ | scope (guests active in an open guest group they lead); never the private status fields |
| `GET /guests/{id}/timeline` | `guests: view` + guests scope; same rules as the member timeline | ✓ (everything) | scope (their guest group only, a former group's rows hidden; status entries with reason and note) |
| `POST /guests/{id}/deactivate` | `guests: deactivate` + guests scope | ✓ | ✗ |
| `POST /guests/{id}/reactivate` | `guests: reactivate` + guests scope | ✓ | 404 in practice (an inactive guest is in no group): they reactivate through the add-guest route |
| `POST /guests` | `guests: create` + `all`; setting on (409); with `smallGroupId` also `smallGroups: manageMembers` + scope | ✓ | — (a new guest comes through a group they lead) |
| `GET /applications/recents`, `/recents/count`, `/{id}` | `membershipApplications: view` | ✓ | — |
| `POST /applications/approve`, `/reject` | `membershipApplications: approve` / `reject` | ✓ | — |
| `GET /people/{id}/events`, `/first-assistance` | `membershipApplications: view` | ✓ | — |
| `GET /care-log/people-search?q=` | `careLog: create`; active members and guests in the members / guests scope (`careLog: all` searches everyone) | ✓ (everyone) | scope |
| `POST /care-log` | `careLog: create` + a linked member (409 `link`) + every person in scope (404 outside, 422 `people` when inactive) + the source visible to the caller (404) | ✓ (anyone) | scope |
| `GET /care-log/{id}` | `careLog: view` + *Care log*'s visibility rule (404 outside it) | ✓ (every entry) | own entries, and `leaders` entries with a person in scope |
| `PATCH`, `DELETE /care-log/{id}` | `careLog: create` + visible + being the author (403 `author`) | ✓ (own only) | ✓ (own only) |
| `POST /care-log/{id}/complete`, `/cancel` | `careLog: create` + visible + author or participant (403 `author`); 409 `not_planned` | ✓ | ✓ |
| `GET /care-log/coming-up` | `careLog: view`; the caller's own planned entries only | ✓ | ✓ |
| `GET /me` | none (any valid JWT) | ✓ | ✓ |
| `PATCH /me/member` | `ownProfile: update`; own linked member only, no scope, no `email` | ✓ | ✓ |
| `GET`, `PUT /me/notification-preferences` | none (any valid JWT): the caller's own email switches (Conversations, Submitted reports, Weekly report reminders) | ✓ | ✓ |
| `GET /me/watched-groups`, `PUT /small-groups/{id}/watch` | the full-scope observation audience (`smallGroups: all` + the conversation read rule), else 403 (before any 404) | ✓ (elders, admins) | ✗ (403: leaders have no watch setting) |

A new role, or a change to what a role can do, is an auth-server change only; nothing here
changes unless a new *action* needs a new check.

## Small group reports (built)

A group files one report per meeting date: the group's prayer, praise and follow-up items plus one attendance row for every member whose membership covers that date. Rules and contracts: `docs/specs/small-group-reports.md` (workspace repo) and `docs/SMALL-GROUP-REPORTS-API-HANDOFF.md`. Code: `api/routers/small_group_reports.py`, `data/small_groups/{queries,results,services}.py`.

- Routes: `GET /small-group-reports` (filed reports and computed not-filed meetings, counts, paging), `GET /small-group-reports/summary` (dashboard), `GET /small-groups/{id}/report-roster?date=`, `POST /small-groups/{id}/reports`, `GET|PATCH|DELETE /small-group-reports/{id}`. Access is `smallGroupReports` permissions plus the small group scope (`SmallGroupScopeDep`, see *Permissions*); closed groups are read-only (409).
- **Observations are private (rule 9).** An attendance row's pastoral `observation` is returned, and editable, only with `smallGroupReports: viewObservations` and for the leaders and co-leaders of the report's group, whoever submitted it. `build_report_detail` decides it once per request and nulls every observation otherwise; the schema then omits the key. Lists and the summary never carry observations.
- "Not filed" is computed, never stored: `recent_meetings` returns, per open group with a meeting day, every date in the last 28 days before today that had a leader or co-leader, with the report id on it or None; `not_filed_dates` is the entries without one.
- **Groups dashboard** (`docs/specs/groups-dashboard.md`, `docs/GROUPS-DASHBOARD-API-HANDOFF.md`). The summary adds `hasLeader` (an open leader or co-leader period today) and `recentMeetings` (the list above, newest first). `GET /small-group-reports/week?date=` (`smallGroups: all` + `smallGroupReports: viewObservations`, since it carries observation *counts*, rule 9) gives every open group's status for the Sunday-to-Saturday week of `date` (default today): `submitted`, `notFiled`, `today`, `upcoming`, `noLeader` or `noMeetingDay`, first match wins (`get_report_week`). It goes up to next week (so it can be marked church-wide); a later week is 422; closed groups never appear.
- **Prayer & follow-up** (`docs/specs/prayer-follow-up.md`, `docs/PRAYER-FOLLOW-UP-API-HANDOFF.md`). `GET /small-group-reports/shared?date=` (`smallGroupReports: view` + scope, no new permission: the items aren't private like observations) gives, for the week of `date` (up to the current week, unlike `/week`; a later week is 422), every held report of the open groups in scope with its `sections` (the items, as in report detail) and the group's leaders today, oldest meeting first; plus `stillToReport`, the scoped groups whose week status is `notFiled`, `today` or `upcoming`. The status comes from the same per-group code as `/week` (`_week_groups`). Each entry's `conversations` holds its section threads (see *Report conversations*), loaded in one query.
- **No meeting** (rule 13, `docs/SMALL-GROUP-NO-MEETING-API-HANDOFF.md`). A leader can record that the group didn't meet on a date: a `small_group_reports` row with `held = false` and an optional `not_held_reason` (≤ 255), no attendance rows, items or address (a CHECK on the address). Create takes `{held: false, meetingDate, notHeldReason}` (a missing `held` means a held report); the unique (group, date) makes a date a meeting or a no meeting, never both. A held report can be created over a no meeting only with `replacesNoMeeting: true` (one transaction); a report never changes kind on PATCH (422); the duplicate 409 carries `existingReportHeld` and the roster's `existingReport` has `held`. It is filed for rule 10 (never Not filed) but is not a Last report, not in `filed` counts (`notHeld` instead), and doesn't take a missed-streak window slot (`held = true` filters in `latest_report_ids_query` and `recent_attendance_marks_query`). The list `status` adds `notHeld`, `recentMeetings[].held` is null when not filed, and the week status adds `notHeld` (no held report but a no meeting). A held report is dated today or earlier; a no meeting up to the end of next week (`_last_no_meeting_date`).
- **Church-wide no meeting** (`docs/specs/church-wide-no-meeting.md`, `docs/CHURCH-WIDE-NO-MEETING-API-HANDOFF.md`). An admin or elder marks a whole week (current, next or past) as no meeting for every group: one `small_group_no_meeting_weeks` row (unique `week_start`, a Sunday; `reason`, `created_by_member_id`) plus a normal no meeting per group, linked by `small_group_reports.no_meeting_week_id` (`ON DELETE SET NULL`, only on a no meeting). `POST /no-meeting-weeks` (`mark_no_meeting_week`) gives every group open today with a meeting day and no report dated in the week (held or not, any day) a no meeting on its meeting day; a re-run (200, not 201) marks the groups still empty and keeps the reason, and a lost race is retried once. `PATCH /no-meeting-weeks/{id}` sets the reason on the week and on every report still linked; a leader's edit of a linked report's reason or date unlinks it (the same values don't), and a held report that replaces one takes it out of the week. `DELETE` (undo) deletes the reports still linked, groups closed since included (not through `delete_report`), then the week. The week endpoint returns `noMeetingWeek` (with `linkedCount`), and reports in the week, list and detail carry `noMeetingWeekId`. The seed marks the week two weeks back.
- **Guests in reports** (`docs/GUEST-SMALL-GROUPS-API-HANDOFF.md`, stage 4). A guest group's roster, attendance rows and detail carry members and guests together: `RosterPerson` and `ReportAttendanceView` hold a `member_id` or a `guest_id`, `PersonKey` (`("member"|"guest", id)`) keys completeness (rule 3), the update-in-place of rows and the missed streaks (`missed_streaks_by_person`), and the API rows gain `person` (no `memberId`/`memberName` on them). Attendance input takes `memberId` or `guestId`. Order: leader, co-leaders, members, then guests, each by name. Every group object in the report shapes carries `audience`. A guest who leaves with `leftAt` = a meeting date stays in that date's roster (`left_at` counts as a day in the group) and out of the next day's.
- **Items and tags** (`docs/specs/report-tags.md`, `docs/REPORT-TAGS-API-HANDOFF.md`, Part 1). A held report's prayer, praise and follow-up are **items**, not text columns: `small_group_report_items` (`section`, `position` from 0, `text`; unique `(report, section, position)`) and one `small_group_report_item_people` row per person tagged in an item (`member_id` or `guest_id`). A body carries `sections: {prayer, praise, followUp}`, each up to 20 items of `segments` (`text` or `person`); it is required on a held body, and an edit replaces every item (ids aren't stable across edits). An item's `text` stores a tag as the token `@{member:198}` / `@{guest:45}`, never a name, so a rename carries through; anything else that looks like a token is plain text. `data/small_groups/report_items.py` converts (`segments_to_text`, `text_to_segments`). Limits: an item is at most 1024 characters with at most 10 people, empty items are dropped; a person must exist, and a *newly* tagged member must be active (re-saving a report where an already-tagged member has since become inactive is fine). Reads return `sections` with each person's current `name` and `viewable` (`members: all` / `guests: all`, else in the caller's scope; computed once per response). `GET /small-groups/{id}/tag-search?q=` finds active members and guests church-wide by name, this group's people first (at most 10, 2+ characters, `[]` for a closed group). The old `groupPrayerRequest` / `groupPraiseReport` / `groupRelevantDiscussion` fields and columns were dropped by migration `ecbadacc8044`, whose downgrade refills them from the items.
- **Person timeline** (`docs/specs/report-tags.md` rules 19-23, `docs/REPORT-TAGS-API-HANDOFF.md`, Part 2). `GET /members/{id}/timeline` and `GET /guests/{id}/timeline` list, newest first, the **held** reports where the person has an attendance row or is tagged in an item (one row even when both), with `groups` (every group with a visible row, any date, for the filter), `earliestDate`, and `counts` (`notes`, `prayer`, `praise`, `followUp`) over the rows returned. Query: `from` / `to` (default: `to` is church today, `from` is three months before it plus a day; 422 with `range` when `to` is in the future, `from` is after `to` or the range is over 731 days), `smallGroupId` (a group with no rows is empty, not 404) or `latest` (1-10, the newest N rows of any date and group; 422 with any of the others). Visibility is per row (rule 23): **attendance, the observation and follow-up items** only for reports of groups in the caller's observation audience (`conversation_group_ids`: every group with `smallGroups: all` + `viewObservations`, else the groups they lead or co-led when closed), **prayer and praise items** that tag the person for any group; a row with nothing visible is dropped and never counted. Items are only those tagging this person, by section then position, as the report detail's segments (`viewable` per rule 12; the person's own is always true). `role` is the person's role on the meeting date from their membership periods (null if none covers it). Code: `api/person_timeline.py` (params, response), `data/small_groups/timeline_{services,queries}.py`. No new permission; the person-keyed indexes already exist. Care log entries are a third source (kind `careLog`, see *Care log*): `counts.careLog` counts them and the four counts above are unchanged.
  - **Typed entries and sources** (`docs/specs/inactive-guests.md` rules 12-15, `docs/INACTIVE-GUESTS-API-HANDOFF.md`). The response's `entries` lists every kind newest first, each with `kind` and `date`: `report` (`report` is the row above) and `status` (`status`, `reason`, `note`, `changedBy` `{ memberId, name }` or null). Status entries come from `member_status_changes` / `guest_status_changes` on `effective_date`, follow the range, are hidden with `smallGroupId`, and show reason and note to everyone who can open the timeline, unlike the detail fields. `latest` cuts across kinds, `earliestDate` is the oldest entry of any kind whatever the range, `groups` and `counts` are reports only (`counts` over the report entries returned).
  - **Adding a kind.** Write a source in `timeline_services.py`, a function of the session and the `_TimelineRequest` (person, caller's access, range or `latest`) returning a `_SourceResult`: its entries filtered for that caller and by date **in the query**, newest first, at most `latest`, plus its own `earliest_date` and `groups` whatever the range. Add it to `_SOURCES`, whose order breaks ties on a date, add the entry to `TimelineEntry` and its schema to `TimelineEntrySchema`. No source knows about the others; staff-app skips a `kind` it doesn't know, so the API can ship one first.
- **Report status and drafts** (`docs/specs/report-autosave.md`, `docs/REPORT-AUTOSAVE-API-HANDOFF.md`). A report is `draft` or `submitted`, on the same `small_group_reports` row, so a draft holds its date like any report. A draft may have null attendance answers and has no submitter; `POST /small-group-reports/{id}/submit` is the one-way way out. It and a create with `status = submitted` are where the report submitted email's event is written (*Report conversations, Part 2: emails*). Every write bumps `version`; a save or submit must send the `version` it is based on (422 without it) and is 409 `changed since` when that is older, checked under a row lock. A create without `status` is a draft. **A draft exists only for the group's current leaders and co-leaders and whoever started it** (`can_see_draft`, `report_visible_to`): no role sees other people's, and for everyone else it is a 404, and 409 `draft is in progress` on its date. They get a label only (`hasDraft`, `existingReport` without an id) and the date stays due / not filed. A read of reports that isn't one of the draft routes filters on `submitted_report_condition()`; a new read must too. The one exception is `reported_group_ids_in_week_query`: a church-wide no meeting skips a group with a draft that week.
- Names in these routes are the member's single stored `name` (members have no first/last name columns).

## Default rate limit

`ApiSettings.default_rate_limit` is `300/minute` per authenticated user (it was `60/minute`). The staff app makes several server-side calls to this API for each page it renders (the page's data, `/me`, the inbox badge), so a handful of page loads a minute used up 60. Stricter per-route limits (writes, approve/reject) are unchanged. The in-memory store still means the figure is per worker and replica; see `api/rate_limit.py`.

## Report conversations (built, Part 1: in-app only)

Elders and admins start a thread about one person's attendance row in a report, or about one of its texts (a **section thread**: `prayer`, `praise`, `followUp`, added by `docs/PRAYER-FOLLOW-UP-API-HANDOFF.md`); the group's leaders reply. Rules and contracts: `docs/specs/report-conversations.md` (workspace repo) and `docs/REPORT-CONVERSATIONS-API-HANDOFF.md`. Code: `api/routers/report_conversations.py`, `data/small_groups/{conversation_queries,conversation_services}.py`, models `report_conversation*.py`. Emails are Part 2, in the next section.

- **Anchor.** A thread is about a member (`member_id`) or a section (`section`, VARCHAR + CHECK), exactly one (CHECK `one_anchor`); unique `(report_id, section)` next to `(report_id, member_id)`. The API anchor is `{ type: "attendance", memberId }` or `{ type: "section", key }`; `member` is null on section threads and inbox rows. Starting a section thread needs text in the section (422 `This section is empty.`; a no meeting has none), replying doesn't; an unknown key is 422 `Unknown section …`. In code one `ConversationAnchor` (member id or `ReportSection`) goes through the lookup and `add_comment`; a section thread can start only when the section has items (`section_has_items_query`). Everything else (audience, sides, unread, resolve, inbox, cascade) is the same for both.
- **Guests.** The anchor can also be a guest's row (`guest_id`; CHECK `one_anchor` is `num_nonnulls(member_id, guest_id, section) = 1`, unique `(report_id, guest_id)`): API anchor `{ type: "attendance", guestId }`, routes `…/conversations/guests/{guestId}[/comments]`, `person: { type, id, name }` on summaries, threads and inbox rows (there is no `memberId`/`memberName`/`member` on them: read `person`; the inbox row's `group` has `audience`). In code `ConversationAnchor` is a `PersonKey` or a `ReportSection`. Starting needs the guest's attendance row (422 otherwise). Everything else below is shared.
- **Tables.** `report_conversations` (unique `(report_id, member_id)`, `report_id` ON DELETE CASCADE, so deleting a report deletes its threads; `last_comment_at/side/user_id` denormalised, plus `last_activity_at`: the newest comment's time counting deleted ones, never moved back, migration `096025ed70a6`), `report_conversation_comments` (soft delete via `deleted_at`, `body` kept but never returned), `report_conversation_comment_revisions` (the text before each edit, never returned) and `report_conversation_reads` (`last_read_at` per user and thread). User ids are auth-server strings with no FK.
- **Audience.** Whoever may see the report's observations (rule 9): `viewObservations` plus the report inside their scope, or a scoped leader/co-leader of the group (a closed group's leaders when it closed). `conversation_access` (`api/access.py`) answers 404 outside the scope and 403 outside the audience; the lists use `conversation_group_ids`. No new permission.
- **Writes** need a linked member (409 `Link your account to a member to comment.`), including edit, delete, resolve and reopen. A comment's `side` is `elders` with `smallGroups: all` at write time, else `leaders`, and is stored. Closed groups stay writable (their reports don't).
- **Status and unread.** `open`/`resolved`; a new comment reopens, and `resolve` takes `{ lastCommentId }` (the newest comment the caller saw) and answers 409 with the current thread if a newer live comment exists, so nobody resolves over a comment they never read. Unread = newest comment is someone else's and newer than your `last_read_at` (marked by `POST …/read`, never by a GET; commenting marks the author's own read). Needs my reply = open and the newest comment is on the other side. Deleting a comment recomputes `last_comment_*` from the newest remaining one (all deleted: unchanged). Writers lock the thread row, and times come from `clock_timestamp()`.
- **Inbox.** Tabs `reply`, `unread`, `open`, `resolved`. One page query (ids first, then joins and a `LATERAL` newest-comment lookup for those rows), one `COUNT(*) FILTER` for the four tab counts (they ignore `smallGroupId` and `resolvedSince`), **`resolvedSince`** (Part 1d, rule 15, `docs/RESOLVED-PERIOD-API-HANDOFF.md`): an offset-aware instant, only with `tab=resolved` (422 otherwise), that keeps threads with `resolved_at >= resolvedSince` in `_tab_threads`, so `total` and the page agree; the staff app turns its period (*Last 30 days*, …) into the instant, and no index was added for it, and, for the sidebar badge (`GET /report-conversations/counts`), one `SELECT` of a bare `COUNT(*)` for `needsMyReply` (the gold number stays *Needs my reply* only) and **`hasUnread`** (Part 1c, rule 17, `docs/UNREAD-DOT-API-HANDOFF.md`): an `EXISTS` over the *Unread* tab's own `FROM`/`WHERE` (`_tab_threads`, no group filter), so it is true exactly when `counts.unread > 0`; the staff app shows it as a dot only while the number is 0. **Unread tab** (Part 1b, rule 17, `docs/UNREAD-TAB-API-HANDOFF.md`): threads unread for the caller, any status; the condition is SQL (`_unread` in `conversation_queries.py`, the twin of `is_unread`) against the caller's read row, shared by the count, the total and the page, so they agree. **`POST /report-conversations/read-all?smallGroupId=`** (*Mark all read*, same permission and audience as the inbox, no linked member needed) upserts a read row for every thread in the audience (and group), any status, at `greatest(existing, last_activity_at)`, never `now()`, so a comment that commits meanwhile stays unread and the mark passes a deleted newest comment. One statement (the upsert is a data-modifying CTE); returns `{ marked }`, the threads that were unread. A group outside the audience marks nothing (`marked: 0`, no 404).
- `ReportDetailSchema.conversationCount` feeds the delete dialog.

## Report conversations, Part 2: emails (built)

Two kinds of email, both by email through auth-server and the same outbox, worker and
`notifications/` layer: **conversation emails** (who hears about a comment) and **report submitted
emails** (a group's watchers hear that its report was submitted). Rules and contracts:
`docs/specs/report-conversations.md` (workspace repo; rules 18-23, *Contracts (Part 2: email)*),
`docs/specs/report-submitted-emails.md`, and the handoffs `docs/REPORT-CONVERSATIONS-EMAIL-API-HANDOFF.md`
and `docs/REPORT-SUBMITTED-EMAILS-API-HANDOFF.md` (their *Decisions and deviations* hold the detail).
auth-server's side: `auth-server/docs/REPORT-CONVERSATIONS-EMAIL-HANDOFF.md`,
`auth-server/docs/REPORT-SUBMITTED-EMAILS-HANDOFF.md`.

- **Switches.** One per kind, in `notifications/config.py` (read by the API and the worker):
  `CONVERSATION_EMAILS_ENABLED` and `REPORT_SUBMITTED_EMAILS_ENABLED`, both default off. Off means
  that kind writes no outbox rows (so no emails, no fast path); with both off there is no worker and
  no auth-server call. Either on needs `INTERNAL_API_TOKEN` in every environment (startup error
  otherwise), sent as `X-Internal-Token` to auth-server's `/internal/*` at `AUTH_SERVER_URL`.
  `EMBEDDED_WORKER` (default on, `ApiSettings`): run the worker inside the API process.
- **Event first.** `add_comment` writes the comment and one `outbox_events` row
  (`report_conversation.comment_added`, payload v1: ids and facts, `occurredAt` = the comment's
  `created_at`) in one transaction, due 60 s later, deadline 24 h. Nothing else in the request.
  Likewise `create_report` (status `submitted`, held or no meeting) and `submit_report` write
  `small_group_report.submitted` (payload v1: `reportId`, `smallGroupId`, `submittedByMemberId`,
  `occurredAt` = `submitted_at`) in the submit's transaction. Drafts, saves, edits, deletes and
  church-wide no meetings (`_mark_no_meeting_week`) write none.
- **One rule for reading and emailing** (rule 23). `data/small_groups/access_rules.py` holds
  `SmallGroupScope`, `small_group_scope_for` and `can_read_group_conversations` as pure functions;
  `api/access.py` (scope, `conversation_access`, `conversation_group_ids`, `ensure_watch_audience`)
  and the worker both call them. It lives outside `api/` because the worker imports nothing from
  FastAPI.
- **Domain consumer** (`data/small_groups/conversation_notifications.py`): the candidate snapshot
  (`candidate_user_ids`, read-only), then inside the event's transaction `process_comment_added`:
  recipients (`choose_recipients`: elders' side → the group's leaders, a closed group's leaders when
  it closed; leaders' side → watchers minus opt-outs; a reply → other live commenters too; never
  the author; `participant` > `leader` > `watcher`), the read check on the pinned permissions
  (`readers_of_group`), the atomic throttle (`pass_throttle`, one statement sorted by user id,
  stamped with `occurredAt`: one email per thread until you open it), then the payload (`path` by
  anchor: `?person=`, `?guest=`, `?section=`). It hands requests to `notifications/` and never reads
  preferences. Category `report_conversation`.
- **Report submitted consumer** (`data/small_groups/report_submitted_notifications.py`): candidates
  are the possible watchers minus the submitter's linked user; `process_report_submitted` keeps the
  readers of the group (`readers_of_group`, the same rule 23 check), drops watch opt-outs and queues
  `report.submitted` (category `report_submitted`, `reason: watcher`, path `/groups/reports/{id}`).
  Names and counts are read at processing time (`attendedCount`/`peopleCount` only for a held
  meeting; no free text, no member names). A report gone or not submitted: processed, no
  deliveries. No throttle. Leaders are never possible watchers, so they never get one.
- **Weekly report reminder** (`docs/specs/report-reminder-emails.md`, `docs/REPORT-REMINDER-EMAILS-API-HANDOFF.md`).
  Trigger: `worker/reminder_trigger.py` (`run_once`, after `expire_overdue`) writes one
  `small_group_report.reminder_due` event per church week when `scheduled_at <= now < scheduled_at +
  6 h` (`REPORT_REMINDER_DAY` ISO weekday, 7 = the week's own Sunday; `REPORT_REMINDER_TIME`; both in
  `CHURCH_TIMEZONE`), inserting `week_start` into `report_reminder_runs` (`ON CONFLICT DO NOTHING`) in
  the same transaction, so sweeps and replicas can't double it. The event and its deliveries expire at
  `scheduled_at + 6 h`, so nothing fires late after an outage. Consumer
  (`data/small_groups/report_reminder_notifications.py`): candidates are the active leaders and
  co-leaders (active member, linked user) of open groups with no submitted report dated in the week;
  none in a church-wide no-meeting week. `process_report_reminder` keeps users holding `smallGroups:
  view` and `smallGroupReports: create`, and queues one `report.reminder` per person (category
  `report_reminder`) listing their groups by name then id with `hasDraft`; the link is `/groups/reports`
  (2+ groups), `/groups/reports/new?groupId=` or `/groups/reports/{latestDraftId}/edit`. Names and the
  draft flag only; no report content.
- **Dispatch.** `worker/events.py` picks each event's consumer (`candidates`, `process`) from
  `_KNOWN` by `event_type` and `schema_version`; anything else goes `dead`.
- **Generic `notifications/`**: `deliveries.py` (`create_deliveries`: drops users whose
  `(category, channel)` preference is off, inserts `ON CONFLICT DO NOTHING`; `is_enabled`),
  `preferences.py`, `sender.py` (the `Sender` protocol), `auth_server.py` (the client: watchers,
  permissions in chunks of 500, `AuthServerSender` mapping auth-server's answers to sent / dead /
  transient), `sending.py` (`send_due_deliveries`).
- **Tables.** `outbox_events`, `notification_deliveries` (unique `(source_event_id,
  recipient_user_id, channel)`, `expires_at` inherited from the event), `notification_preferences`
  (no row = on), `report_conversation_notify_state` (throttle), `small_group_watch_opt_outs` (no
  row = watching), `report_reminder_runs` (one row per church week triggered). The two queues share the claim columns (`data/claim_columns.py`); events and
  deliveries have no foreign keys. Migration `b453135219c0`; `report_reminder_runs` is `7e1a4c9b2d58`.
- **Claiming** (`data/claiming.py`, both queues): one statement leases a batch of 10 with `FOR UPDATE
  SKIP LOCKED` (new claim token, `attempts + 1`, lease 2 min) and turns rows past their deadline into
  `expired` and rows at 5 attempts into `dead`. Every later write is fenced on the token; for events
  the fence is the first statement of the processing transaction. Outcomes: transient (dependency
  trouble: attempt given back, `failures + 1`, never `dead`), exception (attempt kept), permanent
  (`dead`). Backoff by `failures`: 1, 5, 15, 60 min, then hourly. A transient send error stops the
  batch and releases the rest.
- **The worker** (`worker/`, runs while any switch is on): `runner.run_once()` expires overdue rows, triggers the weekly report reminder when due, fetches the possible watchers
  (auth-server unreachable → claims nothing from either table), drains events then deliveries (at
  most 10 batches each), purges final rows (events after 30 days, deliveries after 90) and logs the
  oldest not-final row's age and the `dead` count per table. `run_forever` repeats it every 2
  minutes after a random 0-30 s start. Embedded: the API's `lifespan` runs it on one thread through
  its own `CapacityLimiter(1)` and stops it before disposing the engines. Standalone: `python -m
  membership_management.worker` (SIGTERM/SIGINT stop it after the item in hand). Moving it out is
  `EMBEDDED_WORKER=false` plus a task definition. The stop flag is checked between items.
- **Fast path.** The three comment routes and the two submit routes (`POST
  /small-groups/{id}/reports` when it submits, `POST /small-group-reports/{id}/submit`) queue
  `worker.fast_path.run_fast_path(event_id)` with `BackgroundTasks`: after the response, that one
  event (still `pending`, head start skipped) and its deliveries, through the same claim code.
  Best-effort; the sweep covers it.
- **Routes.** `GET /me/notification-preferences` → `{ email: { reportConversation, reportSubmitted, reportReminder },
  available: { reportConversation, reportSubmitted, reportReminder } }` (any signed-in user;
  `available` is each kill switch, so staff-app can hide a switch). `PUT` takes `{ email: { …any
  subset } }` (unknown keys and a null value inside a channel are 422; a null or missing channel is
  left as it is) and returns the same shape; Part 2 adds `push` and
  `availablePush` (below). Watching is shared by the
  first two kinds only; the reminder switch is independent of it.
  `GET /me/watched-groups` → `{ items: [{ smallGroupId, name, closed, watching }] }` (every group,
  open first) and `PUT /small-groups/{id}/watch` `{ watching }` → `{ smallGroupId, watching }`, both
  for the full-scope audience only (403 first, then 404). Watching changes nothing in the app.

## Notifications, Part 1: the in-app list (built)

Spec `../docs/specs/notifications.md` (Part 1), handoff `docs/NOTIFICATIONS-API-HANDOFF.md`. Every
notification the three consumers email also becomes one row in `user_notifications` per recipient
(migration `ea20b44459b8`): the same `template`, `data` and `path` as the email, a `category`, a
`subject_key` (`report_conversation:{id}`, `small_group_report:{id}`, `report_reminder:{Sunday}`),
`small_group_ids` on reminder entries only, `read_at`. Unique `(source_event_id, user_id)`; no foreign
keys (events live 30 days, entries 90).

- **Writing.** Each consumer hands `EntryRequest`s to `notifications/entries.py` (`create_entries`,
  generic like `create_deliveries`) in the event's transaction, for exactly the recipients it decided
  (audience, Watching, throttle, never the submitter, reminder eligibility) and **before** any email
  preference: in-app has no switch. A kind writes entries only while its own flag AND
  `IN_APP_NOTIFICATIONS_ENABLED` are on (default off). On its own, the flag keeps the worker running
  only for maintenance (the 90-day purge), with no calls to auth-server (`worker_enabled`).
- **Routes** (all `/me`, any signed-in user, camelCase). `GET /me/notifications?limit=20&before={id}`
  → `{ items: [{ id, category, template, data, path, createdAt, readAt }], nextBefore }` (`limit`
  1-50, newest first, `nextBefore` null on the last page). `GET /me/notifications/unread-count` →
  `{ enabled, unread }`, never 404, one count over the partial index on unread rows.
  `POST /me/notifications/{id}/read` → `{ path }`, idempotent, 404 when it isn't the caller's or is
  gone. `POST /me/notifications/read-all` → `{ marked }`. Everything but the count is 404
  `notifications_disabled` while the flag is off.
- **Read state.** `POST /report-conversations/{id}/read` and `read-all` also read the caller's entries
  for those threads, in the same transaction (rule 13, while the flag is on). A report becoming
  submitted (`_on_report_submitted`, both submit paths) marks read the reminder entries of its church
  week whose groups have now all submitted (rule 14, `clear_reminder_entries`).
- **Purge.** The worker's maintenance deletes entries older than 90 days by `created_at`, in bounded
  batches (`purge_entries`, `purged["notifications"]` in the log line).

## Notifications, Part 2: push (built)

Spec `docs/specs/notifications.md` (workspace repo, Part 2, step 4); this side:
`docs/PUSH-NOTIFICATIONS-API-HANDOFF.md`. auth-server owns subscriptions and the fan-out to devices.

- **Flag.** `PUSH_NOTIFICATIONS_ENABLED` (default off, needs `INTERNAL_API_TOKEN`). A kind sends push
  only while its own flag AND this one are on (`NotificationSettings.push_enabled_for`). No worker
  change: push only exists while a kind flag is on, which already runs the worker.
- **One more delivery per recipient.** Each consumer decides recipients once; `notifications/push.py`
  (`push_requests`) turns its email requests into `channel = "push"` ones (same template, data, path),
  and `create_deliveries` applies the per-`(user, category, channel)` preference (no row = enabled) and
  stores them next to the email rows (unique per event, user and channel). The stored payload is the
  envelope auth-server receives: `{ recipientUserId, template, data, path, channel: "push",
  notificationId, badgeCount }`.
- **`notificationId` and `badgeCount`.** `create_entries` returns each recipient's entry id and unread
  count in the event's transaction (a retried event reads the existing rows back). `notificationId` is
  null and `badgeCount` 0 while in-app is off (no entries exist).
- **Sender.** 404 `no_push_subscription` → `dead`, logged at info (no device left is normal); 503
  `send_failed` is a transient like any 5xx. The sender and the claim path are channel-agnostic.
- **Preferences.** `GET /me/notification-preferences` also returns `push: { reportConversation,
  reportSubmitted, reportReminder }` (same categories as email, `channel = "push"`) and
  `availablePush` (each kind's flag AND the push flag). `PUT` takes any subset under `email` and/or
  `push`; an older client sending only `email` works. No migration (`channel` is a plain string).

## Guests and guest groups (built)

People who aren't members take part in guest groups and their reports, never mixed into `members`. Rules and contracts: `docs/specs/guest-small-groups.md` (workspace repo, *rule N* below); this side: `docs/GUEST-SMALL-GROUPS-API-HANDOFF.md`. Code: `data/guests/` (`models/guest.py`, `services.py` for writes, `lookup_services.py` for list/search/detail, `queries.py`, `results.py`), `api/routers/guests.py`, and the guest routes in `api/routers/small_groups.py`.

- **Setting.** `GUEST_GROUPS_ENABLED` (`ApiSettings.guest_groups_enabled`, default off; moves onto the church with multi-tenancy). `GET /me` returns `features.guestGroups`. Off: creating a guest group or a guest is 409 (`ensure_guest_groups_enabled`); reading and everything else on existing guest data keeps working (rule 1).
- **Tables.** `guests` (name, phone, email, sex, address, first visit, `invited_by_member_id`, `created_by_member_id` null for an unlinked creator, `created_at`, `legacy_id`; email is not unique, rule 3). `small_groups.audience` (`members` | `guests`, VARCHAR + CHECK, fixed at creation: `PATCH` with it is 422) with `UNIQUE (id, audience)`. `small_group_members` gains `guest_id`, a copy of the group's `audience`, `left_reason` (`stopped_coming`, `moved_group`, `other`) and nullable `member_id`.
- **The database enforces the rules (rules 5–7).** CHECK `num_nonnulls(member_id, guest_id) = 1` (also on attendance rows); CHECK `guest_id IS NULL OR (audience = 'guests' AND role = 'member')` (a guest is never a leader); composite FK `(small_group_id, audience)` → `small_groups (id, audience)` (a guest can't be in a member group, and a group's audience can't change under its memberships); partial unique `(guest_id) WHERE left_at IS NULL` (one active guest group per guest, across groups). Every insert goes through `SmallGroupMember.for_group`, which sets the relationship and `audience`.
- **Search indexes.** `guest_search_text(text)` (migration) is an IMMUTABLE wrapper of `lower(unaccent(...))`, because `unaccent()` is only STABLE; trigram GIN indexes (`pg_trgm`) on `guest_search_text(name)` and on the phone's digits serve the `LIKE %q%` searches. Queries must use the same expressions (`data/guests/queries.py`); the phone one with SQL literals.
- **Guest groups (rule 6, 7).** `POST /small-groups/{id}/guests` takes `guestId` or `newGuest`, `joinedAt`, `moveFromOtherGroup` and `reactivate` / `reactivateNote` (see *Status*). A guest active in another guest group is 409 `in another group` with `otherGroup {id, name, joinedAt}` (only that; the caller may not have the group in scope); with the flag the old period ends the day before (the same day if it started that day) with `moved_group`, in one transaction. `DELETE …/guests/{guestId}` takes `{leftReason, leftAt}`: `leftAt` defaults to today and is never before the period's start or before the latest report of the group that has the guest's row (422), so filed reports stay complete. Group detail rows carry `person`, guest rows `missedStreak` and `lastAttendedDate`, and counts are split (`memberCount`, `guestCount`; the list's `activeMemberCount` is members only, `activeGuestCount` guests).
- **`/guests` scope (rule 17).** `GuestScopeDep` (`api/access.py`): `guests: all`, or the guests with an open period in an open guest group the caller leads or co-leads today; 404 outside it. Search is church-wide but only for who has `all` or leads such a group (otherwise `[]`) and returns exactly `id, name, phoneLast4, status, inactiveSince, currentGroup | lastGroup, lastAttendedDate` (rule 14). Detail shows the group history and the last 12 attendance rows; a scoped caller gets only the rows of groups they lead, and an observation needs `viewObservations` or leading that row's group.
- **Status** (`docs/specs/inactive-guests.md`, `docs/INACTIVE-GUESTS-API-HANDOFF.md`). `guests.status` (`active` | `inactive`, VARCHAR + CHECK) says whether the person is still around and is **separate from being in a group**: an active guest may be in no group. `status` and `status_changed_at` copy the latest row of the append-only `guest_status_changes` in the same transaction. `POST /guests/{id}/deactivate` takes `{ reason, effectiveDate, note? }` and ends the open period with `left_at` = church today and `left_reason = 'guest_inactive'`, a value **written only by deactivation** and refused in the remove body; `effectiveDate` (the date they left, today or earlier, else 422) is only recorded. `POST /guests/{id}/reactivate` restores no group. Since an inactive guest is out of every leader's scope, leaders reactivate with `reactivate: true` on the add-guest route: one transaction, the change dated today whatever `joinedAt` is, ignored for an active guest. An add locks the guest row, so it can't race a deactivation. Inactive guests stay in search, out of the tag picker, and newly tagging one is 422; existing tags stay. 409 bodies with a `code`: `already_inactive`, `already_active`, `guest_inactive`.
- **Errors the staff app tells apart** (a phrase in `detail`): 409 "…guest groups are off…", 409 "This guest is in another group." (+ `otherGroup`), 409 "…already in the small group.", 422 "Only a guest group can have guests.", 422 "A group's audience can't be changed.", 422 "The leave date can't be before…".
- **Not here yet.** Promoting a guest to member, importing, merging duplicates (rule 21).

## Inactive members (built)

A member who left the church is marked inactive, not deleted, and can come back. Rules and contracts: `docs/specs/inactive-members.md` (workspace repo, *rule N* below); this side: `docs/INACTIVE-MEMBERS-API-HANDOFF.md`. Code: `data/members/` (`models/member_status_change.py`, `services.py`, `queries.py`), `api/routers/members.py`, `api/coded_errors.py`.

- **Status.** `members.status` (`active` | `inactive`, VARCHAR + CHECK) and `status_changed_at` are a copy of the latest row of `member_status_changes`, the append-only history (`reason` is required exactly when the new status is `inactive`; `effective_date` is the date they left; `changed_by_user_id` is a JWT `sub` with no FK). Only `deactivate_member` and `reactivate_member` write them, in one transaction with the member row locked (rule 2).
- **Group periods.** Deactivating closes every open `small_group_members` period of the member, in member and guest groups, with `left_at` = `church_today()` (never `effective_date`) and `left_reason = 'member_inactive'` (rule 6). That value is written **only** by deactivation: the leave and move routes don't accept it. Reactivating restores nothing (rule 10), so the member's `pastSmallGroups` are the `member_inactive` periods with the latest `left_at`. A member who is the leader of an open group can't be deactivated (409 `leads_group` with `groups`, rule 7), nor can the caller's own member (409 `self`, rule 8).
- **Private fields (rule 5).** Reason, note and history need `members: setStatus`; everyone who can see a member sees `status` and `inactiveSince`. `member_detail` and `GET /members` decide it from the claims.
- **Kept out (rule 11).** `GET /members` lists active members by default, `options` only active ones, adding to a group, changing a role, setting the leader and linking a user are 409 `member_inactive`, and the internal accepted-invite route skips an inactive member (`linked: false`, logged at info). A scoped caller never sees an inactive member (404) because the members scope needs an open period. Reports, attendance and conversations keep their rows.
- **409 bodies** with a `code` (`already_inactive`, `already_active`, `leads_group`, `self`, `member_inactive`) are `CodedHTTPError`: `{ detail, code, ...extra }`, so the staff app picks the dialog without parsing `detail`.
- **Sign-in** is turned off by staff-app (a ban of the linked user) after the deactivation; this service never calls auth-server (rule 9).

## Care log (built, Part 1 of care)

A record that something happened, or is planned, about one or more members and guests: a call, messages, a meeting, a visit, something we heard, a note. Rules and contracts: `docs/specs/care.md` (workspace repo, *rule N* below); this side: `docs/CARE-API-HANDOFF.md` (stages 1–5). Code: `data/care/` (`models/`, `queries.py`, `services.py`, `results.py`, `access_rules.py`), `api/routers/care_log.py`, `api/care_access.py`, `api/care_log.py`, `api/schemas/care_log.py`, seed `data/seed/care.py`.

- **Tables.** `care_log_entries` (kind `call` | `message` | `meeting` | `visit` | `heard` | `note`; status `done` | `planned` | `cancelled`; `meeting_mode` `in_person` | `online` exactly for meetings; `occurred_on` is a church date, `occurred_at_time` optional; `text` required once done; `heard_from`, `others`, `cancel_reason`; `visibility` `leaders` | `private`; the author as `author_user_id` (a string, no foreign key) and `author_member_id`; source columns; `created_at`, `edited_at`, `deleted_at`), `care_log_entry_people` (the person pair, exactly one, unique per entry), `care_log_entry_participants` (members only, display only) and `care_log_entry_revisions` (the text before each edit or completion, never returned). Enums are VARCHAR + CHECK; the database also refuses planned messages, notes and heard entries (rule 6), a mode on a non-meeting, and a source that doesn't match its kind.
- **Who sees an entry (rule 8): one SQL condition.** `care_log_visible_condition(viewer)` in `data/care/queries.py`: `careLog: all` sees every entry; the author sees their own; `careLog: view` sees `leaders` entries with at least one person in the caller's members scope (`MemberScope`) or guests scope (`GuestScope`) and none of them the caller's own member (the person never sees it; only `careLog: all` and the author are exempt). `api/care_access.py` builds the `CareLogViewer` from the claims and those scopes; every route (`entry_visible` runs the same condition on one id), *Coming up* and the timeline use it, so losing a person from your scope takes their entries away on the next request. Outside it, 404. The person never sees anything. The people a caller may name are the same scope (`careLog: all` has none), active members and guests only (404 out of scope, 422 `people` when inactive; an edit checks only people it adds).
- **Writing (rules 7 and 10).** `careLog: create` plus a linked member (409 `link`, body `code`). Validation errors are 422 `CodedHTTPError`s with a `code`: `kind_status` (only a call, meeting or visit is planned; created as done or planned), `date` (done not in the future, a new plan not in the past, an existing plan may keep its date), `text` (done needs 1–4000 after trimming), `others`, `heard_from` (required, 1–200, for a `heard` entry; refused on other kinds), `meeting_mode`, `people`, `participants`, `reason`, and on edit `status` / `source` / `kind` / `visibility`. The author edits any time (fields but status and source; a changed text keeps the old one as a revision and sets `edited_at`) and soft-deletes (`deleted_at`: gone from every response, the text stays); nobody else does, even an elder (403 `author`). The author or a participant completes a plan (the outcome text and the actual date, never in the future; the purpose is kept as a revision) or cancels it (optional reason; it stays visible as cancelled); anything not planned is 409 `not_planned`, decided under a row lock (`SELECT ... FOR UPDATE`, then re-read), so a complete racing a cancel can't both win.
- **Source (rule 12).** An entry may be logged from an attendance row (`kind: attendance`, report and person), a report section (`kind: section`, `reportId` and `section` `prayer` | `praise` | `followUp`, never an item id: a report edit rewrites every item) or a conversation thread; the caller must see it (attendance rows, the follow-up section and threads: the observation audience, `conversation_group_ids`; the prayer and praise sections: the group's scope; the report submitted) or it is 404. In responses `source` is `{ kind, section, reportId, meetingDate, smallGroup, visible, gone }`: `visible: false` hides the ids from someone who can't open it, `gone: true` after the report or thread was deleted (the foreign keys are `ON DELETE SET NULL`, the kind stays).
- **Response.** `CareLogEntrySchema` (`api/schemas/care_log.py`, built by `api/care_log.py`): people with `viewable` (report tags rule 12), participants (each with `sees`: would that person see the entry, by the same condition for their own user, assuming `careLog: view` without `all` and the groups they lead; being named grants no access), author, `pastDue` (planned and before church today), `canEdit` (author, with `careLog: create`) and `canComplete` (author or participant of a plan, with `careLog: create`). Times are `HH:MM`, `meetingMode` is `inPerson` | `online`.
- **Person timeline (rule 13).** A third source in `data/small_groups/timeline_services.py` (order on a date: status changes, care log entries, reports): the entries about the person the caller sees, not deleted, not cancelled, in the range except plans still ahead (after church today), which are always listed; picking a group hides them. Kind `careLog`: `{ kind, date, entry }`.
- **Coming up (rule 11).** `GET /care-log/coming-up`: the caller's own planned entries (author, or participant) that they can see: `pastDue` (before today, oldest first) and `upcoming` (today through the next 7 days).
- **Seed.** `data/seed/care.py`, last: a member's call from a follow-up item, WhatsApp messages by her group's leader, a past plan, a plan ahead with the leader taking part, an elders-only `heard` entry, and a guest's visit. The elders and leaders have made-up user ids (`seed-elder-N`, `seed-user-<member id>`).
- **Not here yet.** Care (Part 2: cares, owners, the stream, the `care` timeline source, the Care lists), email.

## Infra / deployment target
- Docker → Kubernetes → Terraform, deployed to AWS or GCP.
- Basic CI/CD, likely GitHub Actions.
- Caching and logging as cross-cutting concerns (mechanism TBD).
- Notifications: email and WhatsApp.

## Why this shape
This is primarily a learning project (modern Python/FastAPI stack, agentic dev workflows with Claude Code, eventually a real deployed system) that also needs to work for a small real user base (~20 people at one church).
