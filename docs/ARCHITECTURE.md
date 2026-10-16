# Architecture (target / vision)

This describes where the project is headed, not what's built yet — for current implementation state, see the root `CLAUDE.md`.

## System shape

A single microservice — membership management (assimilation): membership applications, members, small groups and small-group reports — augmenting an existing church web application (SQL Server DB, real users) by adding a new component alongside it rather than extending it directly.

- Uses the **existing SQL Server DB** via SQLAlchemy (this is the code that exists today, under `src/membership_management/data/assimilation/`).
- FastAPI surface to list, review, and approve membership applications.
- Planned areas beyond applications: members management, small groups, and small-group reports.

## Small group reports (built)

A group files one report per meeting date: the group's text fields plus one attendance row for every member whose membership covers that date. Rules and contracts: `docs/specs/small-group-reports.md` (workspace repo) and `docs/SMALL-GROUP-REPORTS-API-HANDOFF.md`. Code: `api/routers/small_group_reports.py`, `data/small_groups/{queries,results,services}.py`.

- Routes: `GET /small-group-reports` (filed reports and computed not-filed meetings, counts, paging), `GET /small-group-reports/summary` (dashboard), `GET /small-groups/{id}/report-roster?date=`, `POST /small-groups/{id}/reports`, `GET|PATCH|DELETE /small-group-reports/{id}`. Access is the leader access scope (`SmallGroupScopeDep`): admin/elder everything, smallGroupLeader/deacon only their groups (404 elsewhere), other roles 403; closed groups are read-only (409).
- **Observations are private (rule 9).** An attendance row's pastoral `observation` is returned, and editable, only for admin/elder and for the report's submitter. `build_report_detail` decides it once per request and nulls every observation otherwise; the schema then omits the key. Lists and the summary never carry observations.
- "Not filed" is computed, never stored: `recent_meetings` returns, per open group with a meeting day, every date in the last 28 days before today that had a leader or co-leader, with the report id on it or None; `not_filed_dates` is the entries without one.
- **Groups dashboard** (`docs/specs/groups-dashboard.md`, `docs/GROUPS-DASHBOARD-API-HANDOFF.md`). The summary adds `hasLeader` (an open leader or co-leader period today) and `recentMeetings` (the list above, newest first). `GET /small-group-reports/week?date=` (admin/elder only, since it carries observation *counts*, rule 9) gives every open group's status for the Sunday-to-Saturday week of `date` (default today): `submitted`, `notFiled`, `today`, `upcoming`, `noLeader` or `noMeetingDay`, first match wins (`get_report_week`). A week after the current one is 422; closed groups never appear.
- Names in these routes are the member's single stored `name` (members have no first/last name columns).

## Infra / deployment target
- Docker → Kubernetes → Terraform, deployed to AWS or GCP.
- Basic CI/CD, likely GitHub Actions.
- Caching and logging as cross-cutting concerns (mechanism TBD).
- Notifications: email and WhatsApp.

## Why this shape
This is primarily a learning project (modern Python/FastAPI stack, agentic dev workflows with Claude Code, eventually a real deployed system) that also needs to work for a small real user base (~20 people at one church).
