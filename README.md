# Membership Management

A Python microservice for church membership management (membership applications, members, small groups and small-group reports), built alongside an existing church web application. Currently implemented: the SQL Server data layer, a CLI, and a FastAPI surface for membership applications.

## Overview

This project serves three objectives:

1. Learning exercise to get up to date with the latest Python stack (primary objective — self-funded, no cost pressure)
2. Learning agentic workflows (GitHub Copilot + Claude Code) during development, working toward an actual agentic dev workflow
3. Real working software, adding a new component (this API) alongside an existing church web app rather than extending it — used by a small real user base (~20 people)

Architecture notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Near-term plan: [docs/ROADMAP.md](docs/ROADMAP.md).

## What's built so far

- **Data layer** (`src/membership_management/data/assimilation/`) — SQLAlchemy models, queries, and service for the existing SQL Server (assimilation) database.
- **Members database** (`src/membership_management/data/`) — this service's own PostgreSQL database (members, small groups with membership/leadership history), with its schema managed by Alembic migrations in `src/membership_management/data/migrations/`.
- **CLI** (`src/membership_management/cli/main.py`) — queries membership applications from the last 30 days and prints them.
- **API** (`src/membership_management/api/`) — FastAPI workspace member with endpoints to list recent applications and placeholder approve/reject endpoints.

## Plan for next steps

See [docs/ROADMAP.md](docs/ROADMAP.md).

## Main packages

- **SQLAlchemy** — ORM for the existing SQL Server database and the members PostgreSQL database
- **Alembic** — schema migrations for the members database
- **psycopg 3** — PostgreSQL driver
- **FastAPI** — REST API for membership applications
- **Pydantic / pydantic-settings** — settings management and request/response schemas

## Requirements

1. Python 3.14
2. uv

## Setup

1. `uv sync --all-packages` — installs root package and workspace dependencies (including the FastAPI workspace member; plain `uv sync` leaves it out)
2. Copy the root `.env.example` to the root `.env` and set `ASSIMILATION_DATABASE_URL` and `MEMBERS_DATABASE_URL`. Use `127.0.0.1` rather than `localhost` for a local Postgres: on Windows `localhost` resolves to IPv6 `::1` first, which hangs forever against Docker Desktop's Postgres.
3. Create the empty members database in Postgres (Alembic creates tables, not databases), then apply the migrations: `uv run alembic upgrade head`

## Running

Run these commands from the repository root so they load the root `.env`. The file is only read when `ENVIRONMENT` is not set to `staging` or `production` in the real environment, so deployments get their config from real env vars alone (see `src/membership_management/env_file.py`). A variable set in the shell always wins over the file.

```powershell
# CLI — list recent membership applications
uv run python -m membership_management.cli.main

# FastAPI dev server — use this for day-to-day local development.
# Auto-reloads on file changes; binds 127.0.0.1:8000; does NOT read
# PORT / keep-alive / graceful-shutdown from .env (fastapi dev doesn't expose those).
uv run --package membership-management-api fastapi dev src\membership_management\api\main.py

# FastAPI production-style server — no auto-reload. Use this to run/test the app
# the way it'll behave in staging, production, or Docker (reads PORT, keep-alive
# and graceful-shutdown timeouts from .env; binds 0.0.0.0).
uv run --package membership-management-api python -m membership_management.api.run

uv run ty check # check typing
uv run ruff check # check linting
```

Request/DB timeouts (connect, query, pool, request, keep-alive, graceful-shutdown, port) are all configurable via `.env` — see `.env.example` for the full list and defaults.

## Seeding the members database

`src/membership_management/data/seed/` fills the members PostgreSQL database with realistic development/demo data set in Managua, Nicaragua: 55 members (Nicaraguan names, `+505` phones, landmark-style Managua addresses, `@example.com` emails), 5 small groups (`GP - #1` … `GP - #5`) with 8–10 active members each including one leader and one co-leader, some membership history (promotions, transfers, members who left), and the last 8 weeks of small-group reports with attendance. The assimilation SQL Server database is never touched.

Apply the migrations first (`uv run alembic upgrade head`), then from the repository root:

```powershell
# Seed an empty database. Refuses if any members-DB table already has rows.
uv run python -m membership_management.data.seed

# Wipe every members-DB table (TRUNCATE ... RESTART IDENTITY) and seed again.
# Destroys whatever data is there; the migration state (alembic_version) is kept.
uv run python -m membership_management.data.seed --reset

# Options
uv run python -m membership_management.data.seed --help
#   --rng-seed N          generate a different (but still reproducible) data set; default 2026
#   --today YYYY-MM-DD    fix the date that join dates and report dates are generated from
```

The data is deterministic: the same `--rng-seed` and `--today` always produce the same rows, so demos and tests are repeatable. Everything is written in one transaction, so a failure leaves the database unchanged. The script refuses to run when `ENVIRONMENT=production`.

To seed a new table, add a `seed_<domain>(ctx)` function in its own module under `data/seed/` (it adds rows through `ctx.session` and uses `ctx.rng`/`ctx.today`, flushing but never committing) and register it in `SEEDERS` in `data/seed/runner.py`, after any seeders whose rows it reads. `--reset` picks up new tables automatically. Static names, neighborhoods and texts live in `data/seed/fixtures.py`.

## Database migrations

Alembic manages the schema of the members PostgreSQL database **only**. The assimilation SQL Server database belongs to the existing church web app and is never migrated from here, and auth-server has its own separate database. Run every command from the repository root.

### Changing the schema

1. Add or change models under `src/membership_management/data/<domain>/models/`, using `MemberManagementBase`. For a new model, export it from its domain's `models/__init__.py`; for a new domain, also import its `models` package in `src/membership_management/data/models.py`. Autogenerate only sees imported models, and treats an existing table whose model it can't see as deleted, so it would generate a `drop_table` for it.
2. Generate a migration:

   ```powershell
   uv run alembic revision --autogenerate -m "short description"
   ```

   The new file lands in `src/membership_management/data/migrations/versions/` and is automatically fixed and formatted by ruff (post-write hooks in `alembic.ini`).
3. **Review the generated file before applying it.** Autogenerate is a draft, not a guarantee. Check that `upgrade()` only contains the changes you intended (no unexpected `drop_table`/`drop_column`) and that `downgrade()` reverses them. Some changes aren't detected and must be written by hand, e.g. new values for the `small_group_members.role` CHECK constraint, or table/column renames, which autogenerate sees as drop + add.
4. Apply it and confirm it can be rolled back:

   ```powershell
   uv run alembic upgrade head      # apply all pending migrations
   uv run alembic downgrade -1      # roll back the latest one...
   uv run alembic upgrade head      # ...and re-apply it
   uv run alembic check             # should print "No new upgrade operations detected"
   ```

Once a migration has run anywhere other than your machine, treat it as immutable and fix mistakes with a new migration instead of editing it.

### Other useful commands

```powershell
uv run alembic current            # revision the database is at
uv run alembic history            # all migrations, newest first
uv run alembic upgrade head --sql # print the SQL without touching the database
```

### Deployments

The Docker image contains no `alembic.ini`, so deployments run migrations through a small entry point that configures Alembic in code:

```powershell
python -m membership_management.data.migrate   # equivalent to `alembic upgrade head`
```

Run it as a one-off task (e.g. an ECS task using the same image) **before** updating the service, never on app startup: multiple replicas would race each other, and a failed migration would crash-loop the service. During a deploy the old version still runs against the new schema, so every migration must stay compatible with the code currently running (e.g. add a column, deploy code that uses it, and drop the old one in a later migration).

## Configuration notes

- **Auth-server settings** (`AUTH_SERVER_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`) — all three are required. `AUTH_SERVER_URL` is where this API *fetches* auth-server's signing keys (JWKS), so in AWS it's the internal address (e.g. `http://auth-server:5000`). `JWT_ISSUER`/`JWT_AUDIENCE` are what every token's `iss`/`aud` must equal: auth-server's `BETTER_AUTH_URL` origin, i.e. the *public* URL (`https://staff.example.org` in prod), with no trailing slash. Locally all three are `http://localhost:5000`.
- **Rate limiting** — per authenticated user (verified JWT `sub`), not per IP: `DEFAULT_RATE_LIMIT` applies across all routes, with stricter per-route limits (approve/reject) added on top; over-limit requests get `429` with `Retry-After`. `RATE_LIMIT_STORAGE_URI` picks where counters live (`memory://` by default; a shared `redis://...` is needed once there is more than one worker or replica). Anonymous per-IP limiting is intentionally not done here — it belongs at the edge (Cloudflare/WAF) and needs revisiting before this API is exposed publicly.
- **DB timeouts and connection pools** — each database has its own prefixed settings (`ASSIMILATION_DB_*` for SQL Server, `MEMBERS_DB_*` for Postgres; see `.env.example`), so they're sized independently. Per DB, a single process holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections, and once running as multiple containers the real ceiling is `(WORKERS x replica count) x (DB_POOL_SIZE + DB_MAX_OVERFLOW)`.
  - **SQL Server** is shared with the existing church web app, so that total needs headroom, not just to stay under SQL Server's hard cap.
  - **Postgres (RDS)**: the instance's `max_connections` (set by its memory size) is shared by this service's pool, auth-server's pool, the migration task and admin tools. The members DB also ends sessions left idle inside a transaction (`MEMBERS_DB_IDLE_IN_TRANSACTION_TIMEOUT_SECONDS`), and migrations give up waiting for a table lock after `MEMBERS_MIGRATION_LOCK_TIMEOUT_SECONDS` instead of stalling the queries queued behind them.
- **`WORKERS`** — uvicorn worker processes in `run.py`. Raising this multiplies the DB pool ceiling above *and* silently changes rate limiting: the rate limiter (`src/membership_management/api/rate_limit.py`) counts in-memory per process by default (`RATE_LIMIT_STORAGE_URI=memory://`), so a "10/minute" route limit becomes "10 x WORKERS per minute" with no error to flag it. Leave at `1` and scale via container replica count once deployed behind an orchestrator (ECS/K8s) instead.
