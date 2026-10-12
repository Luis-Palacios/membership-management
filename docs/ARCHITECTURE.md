# Architecture (target / vision)

This describes where the project is headed, not what's built yet — for current implementation state, see the root `CLAUDE.md`.

## System shape

A single microservice — membership management (assimilation): membership applications, members, small groups and small-group reports — augmenting an existing church web application (SQL Server DB, real users) by adding a new component alongside it rather than extending it directly.

- Uses the **existing SQL Server DB** via SQLAlchemy (this is the code that exists today, under `src/membership_management/data/assimilation/`).
- FastAPI surface to list, review, and approve membership applications.
- Planned areas beyond applications: members management, small groups, and small-group reports.

## Infra / deployment target
- Docker → Kubernetes → Terraform, deployed to AWS or GCP.
- Basic CI/CD, likely GitHub Actions.
- Caching and logging as cross-cutting concerns (mechanism TBD).
- Notifications: email and WhatsApp.

## Why this shape
This is primarily a learning project (modern Python/FastAPI stack, agentic dev workflows with Claude Code, eventually a real deployed system) that also needs to work for a small real user base (~20 people at one church).
