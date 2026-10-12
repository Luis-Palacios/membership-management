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
- **CLI** (`src/membership_management/cli/main.py`) — queries membership applications from the last 30 days and prints them.
- **API** (`src/membership_management/api/`) — FastAPI workspace member with endpoints to list recent applications and placeholder approve/reject endpoints.

## Plan for next steps

See [docs/ROADMAP.md](docs/ROADMAP.md).

## Main packages

- **SQLAlchemy** — ORM for the existing SQL Server database
- **FastAPI** — REST API for membership applications
- **Pydantic / pydantic-settings** — settings management and request/response schemas

## Requirements

1. Python 3.14
2. uv

## Setup

1. `uv sync --all-packages` — installs root package and workspace dependencies (including the FastAPI workspace member; plain `uv sync` leaves it out)
2. Copy the root `.env.example` to the root `.env` and set `ASSIMILATION_DATABASE_URL`

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

## Configuration notes

- **Auth-server settings** (`AUTH_SERVER_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`) — all three are required. `AUTH_SERVER_URL` is where this API *fetches* auth-server's signing keys (JWKS), so in AWS it's the internal address (e.g. `http://auth-server:5000`). `JWT_ISSUER`/`JWT_AUDIENCE` are what every token's `iss`/`aud` must equal: auth-server's `BETTER_AUTH_URL` origin, i.e. the *public* URL (`https://staff.example.org` in prod), with no trailing slash. Locally all three are `http://localhost:5000`.
- **Rate limiting** — per authenticated user (verified JWT `sub`), not per IP: `DEFAULT_RATE_LIMIT` applies across all routes, with stricter per-route limits (approve/reject) added on top; over-limit requests get `429` with `Retry-After`. `RATE_LIMIT_STORAGE_URI` picks where counters live (`memory://` by default; a shared `redis://...` is needed once there is more than one worker or replica). Anonymous per-IP limiting is intentionally not done here — it belongs at the edge (Cloudflare/WAF) and needs revisiting before this API is exposed publicly.
- **DB connection pool** (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`) — total connections a single process can hold against SQL Server. Once running as multiple containers, the real ceiling is `(WORKERS x replica count) x (DB_POOL_SIZE + DB_MAX_OVERFLOW)`, and this DB is shared with the existing church web app, so that total needs headroom, not just to stay under SQL Server's hard cap.
- **`WORKERS`** — uvicorn worker processes in `run.py`. Raising this multiplies the DB pool ceiling above *and* silently changes rate limiting: the rate limiter (`src/membership_management/api/rate_limit.py`) counts in-memory per process by default (`RATE_LIMIT_STORAGE_URI=memory://`), so a "10/minute" route limit becomes "10 x WORKERS per minute" with no error to flag it. Leave at `1` and scale via container replica count once deployed behind an orchestrator (ECS/K8s) instead.
