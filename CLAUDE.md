# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Early-stage: no tests or CI yet, but real code exists beyond the placeholder entry point. Treat architecture notes below as provisional — update this file as real structure gets added.

This is a single microservice for church membership management (membership applications, members, small groups and small-group reports), sitting alongside an existing church web application. See `docs/ARCHITECTURE.md` for this service's architecture and `docs/ROADMAP.md` for near-term plan — don't inline that detail here; this file should stay short since it's loaded into every agent session.

## Commands

This project uses [uv](https://docs.astral.sh/uv/) with the `uv_build` backend (Python >=3.14, pinned via `.python-version`).

- Sync dependencies / create the venv: `uv sync --all-packages` (plain `uv sync` only syncs the root
  project's own dependencies, not workspace members like `src/membership_management/api` — it will
  silently *uninstall* `fastapi`/`pyjwt`/etc. if they were previously synced in, since they're not a
  root-level dependency)
- Run the console script (currently just the placeholder `main()`): `uv run membership-management`
- Run the actual CLI logic (lists recent membership applications): `uv run python -m membership_management.cli.main`
- Run the FastAPI development server (use for day-to-day local coding — auto-reloads, binds 127.0.0.1, ignores `PORT`/`WORKERS`/keep-alive/graceful-shutdown/`limit_concurrency`/`backlog` from `.env`, since it never calls `run.py`'s `uvicorn.run()`): `uv run --package membership-management-api fastapi dev src\membership_management\api\main.py`
- Run the FastAPI production-style server (use whenever a change touches one of the uvicorn-level settings above and you need to see it actually take effect locally, not just for staging/production/Docker — no auto-reload, binds 0.0.0.0, reads `PORT`, `WORKERS`, keep-alive/graceful-shutdown timeouts, and `limit_concurrency`/`backlog` from `.env`): `uv run --package membership-management-api python -m membership_management.api.run` (invokes `uvicorn` directly rather than `fastapi run`, since `fastapi run` can't set those uvicorn-level flags)
- Build the package: `uv build`
- Lint: `uv run ruff check .` (config in `ruff.toml`); pre-commit hooks are set up via `.pre-commit-config.yaml`
- Type-check: `uv run ty check` ([`ty`](https://github.com/astral-sh/ty), Astral's type checker — no separate config file yet)

Run commands from the repository root so settings load the root `.env`. `.env` is skipped when `ENVIRONMENT` is `staging`/`production` in the real environment (`env_file.py`), so deployments use real env vars only.

## Architecture

- Packaging: `pyproject.toml` defines a console script `membership-management` that maps to `membership_management:main` (still the placeholder — not yet wired to real logic). `src/membership_management/api` is a separate `uv` workspace member with its own `pyproject.toml`.
- `src/membership_management/cli/main.py` — queries membership applications generated in the last 30 days from the assimilation DB and prints them.
- `src/membership_management/api/main.py` — FastAPI app: `GET /applications/recents` returns recent applications via the same service layer as the CLI; `POST /applications/approve` and `/applications/reject` are placeholders that don't yet persist status changes. `GET /health` pings the DB and reports this process's connection-pool stats (`size`/`checked_out`/`overflow`) alongside the `SELECT 1` check. A `lifespan` hook sets anyio's default thread-pool limiter from `ApiSettings.thread_pool_size` on startup (bounds concurrent sync `def` routes/dependencies) and calls `engine.dispose()` on shutdown.
- `src/membership_management/api/config.py` — `ApiSettings`: CORS origins, `port`, `workers`, request/keep-alive/graceful-shutdown timeouts, the default rate limit, uvicorn's `limit_concurrency`/`backlog`, and `thread_pool_size` (see `.env.example`). `workers > 1` multiplies the DB pool ceiling (each worker is a separate process/engine/pool) and silently breaks the in-memory rate limiter's per-route counts — see `rate_limit.py`. `thread_pool_size` bounds concurrent sync (`def`) route handlers separately from the DB pool — if it's smaller than `db_pool_size + db_max_overflow`, it becomes the binding concurrency limit instead of the DB pool.
- `src/membership_management/api/middleware.py` — `RequestLoggingMiddleware` and `RequestTimeoutMiddleware` (returns 504 past `REQUEST_TIMEOUT_SECONDS`).
- `src/membership_management/api/rate_limit.py` — per-user rate limiting built directly on the `limits` library (moving-window strategy), not a slowapi middleware. `rate_limit(spec, scope=...)` returns a FastAPI dependency that runs after JWT verification and keys on the verified `sub`; `default_user_rate_limit` (from `ApiSettings.default_rate_limit`) is attached to every router, and stricter per-route limits (approve/reject) are added as route-level `dependencies=[...]`. Over-limit requests get 429 with `Retry-After` and `RateLimit-*` headers. Storage comes from `ApiSettings.rate_limit_storage_uri` (`memory://` by default, so counters aren't shared across `ApiSettings.workers` or replicas — a "60/minute" limit becomes "60 x (workers x replicas) per minute" if either is raised; use a shared Redis URI to fix that). Deliberately no per-IP limiting of anonymous traffic: that belongs at the edge (Cloudflare/WAF), and needs revisiting before this API is exposed publicly.
- `src/membership_management/api/run.py` — production-style entry point (`python -m membership_management.api.run`, no auto-reload): calls `uvicorn.run()` directly so `port`, `workers`, keep-alive/graceful-shutdown timeouts, and `limit_concurrency`/`backlog` from `ApiSettings` take effect. Use `fastapi dev` instead for local coding.
- `src/membership_management/data/query_helpers.py` — `first_as`/`all_as` map SQLAlchemy `Select` rows onto a dataclass or `NamedTuple` by column name.
- `src/membership_management/data/assimilation/` — SQLAlchemy data layer for the existing SQL Server DB (the "assimilation" system):
  - `config.py` — pydantic-settings `Settings`, loaded from env vars and, outside staging/production, the root `.env` (see `env_file.py`). `ENVIRONMENT` is required; `DEBUG` defaults to `False` and is rejected in production (see `.env.example`; requires `ASSIMILATION_DATABASE_URL`). Also holds the connection-pool settings (`db_pool_size`, `db_max_overflow`, `db_pool_pre_ping`, `db_pool_use_lifo`) consumed by `database.py`.
  - `database.py` — SQLAlchemy `engine` (pool sized/tuned from `Settings`; `pool_reset_on_return="rollback"` is fixed, not configurable), `SessionLocal`, declarative `Base`.
  - `models/membership_applications/` — the `MembershipApplication` model (maps to existing `MemberShipApplications` table), `queries.py` (typed `Select` builders), `services.py` (business/query-window logic, e.g. the 30-day recent-applications window), and `results.py` (`NamedTuple` result types).
  - `models/person/person.py` — the `Person` model (maps to the existing `Persona` table), joined against membership applications.
- The FastAPI routes call the `services.py` functions directly (no repository abstraction layer) — see `docs/ROADMAP.md` for how that decision was reached and what's still open.
