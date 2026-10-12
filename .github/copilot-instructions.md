# Copilot Instructions

## Commands

Run commands from the repository root so settings read the root `.env` (skipped when `ENVIRONMENT`
is `staging` or `production` in the real environment; see `env_file.py`).

- Install or refresh all workspace dependencies: `uv sync --all-packages`. Plain `uv sync` omits the
  API workspace member and can remove its dependencies.
- Build the root package: `uv build`.
- Lint: `uv run ruff check .`. Ruff uses a 110-character line limit and enforces annotation, async,
  type-checking-import, naming, security, and import-sorting rules.
- Type-check: `uv run ty check`.
- There is no test suite or test runner yet, so neither a full-suite nor a single-test command
  exists. Add the appropriate `uv run <runner> path\to\test.py::test_name` command here when tests
  are introduced.
- The `membership-management` script is still a placeholder. Run the implemented CLI with
  `uv run python -m membership_management.cli.main`.
- Start the API for day-to-day development with
  `uv run --package membership-management-api fastapi dev src\membership_management\api\main.py`.
  For production-style behavior, including configured Uvicorn settings, use
  `uv run --package membership-management-api python -m membership_management.api.run`.

## Architecture

- This is a single membership-management microservice (membership applications, members, small
  groups and small-group reports) alongside an existing church application.
  Its current implementation is a synchronous SQL Server assimilation data layer consumed by a CLI
  and a FastAPI workspace member at `src/membership_management/api`. The API has its own
  `pyproject.toml`; keep FastAPI-specific dependencies and configuration there.
- Settings load from env vars and, outside staging/production, the root `.env`; start with
  `.env.example`. `ENVIRONMENT` is required, and `DEBUG` defaults to `False`. Importing the assimilation layer
  requires `ASSIMILATION_DATABASE_URL`. Never commit credentials.
- `data/assimilation/database.py` owns the SQLAlchemy engine, `SessionLocal`, and declarative
  `Base`. The CLI owns session lifetime with a context manager; FastAPI routes receive sessions from
  the `get_assimilation_db` yield dependency.
- Keep each data feature split across its model, typed `queries.py` query builders, `services.py`
  application behavior, and `results.py` projected `NamedTuple` values. `query_helpers.py` maps
  result rows by selected-column name, so selected names (and any necessary aliases) must exactly
  match result constructor fields. API and CLI callers consume these projected values rather than
  ORM instances.
- The recent-membership-application service uses a 60-day window relative to the newest persisted
  application, falling back to the current UTC time when no applications exist. Preserve that
  anchor behavior unless changing the feature contract.
- API routers call services directly; there is intentionally no repository abstraction. Approval
  and rejection endpoints are placeholders and do not persist status changes or publish events.

## Conventions and operational constraints

- Map the legacy SQL Server schema exactly, including its table and column casing. Use modern
  SQLAlchemy 2.x declarative types (`Mapped`, `mapped_column`, `relationship`) and explicit
  `Session` annotations.
- The assimilation layer deliberately uses synchronous SQLAlchemy and `pyodbc`. Database-backed
  FastAPI handlers must be regular `def` functions so FastAPI runs them in its worker thread pool;
  do not introduce SQLAlchemy asyncio piecemeal.
- Keep annotation-only imports under `TYPE_CHECKING`; add `from __future__ import annotations` when
  forward references avoid runtime imports.
- Protected API routers authenticate JWTs before applying rate limits. Limits are per verified JWT
  `sub`; with the default `memory://` storage, counters are per process. Configure a shared
  `RATE_LIMIT_STORAGE_URI` before increasing `WORKERS` or replicas, or the effective limit
  multiplies per process.
- Each Uvicorn worker has its own SQLAlchemy pool. Keep
  `(workers x replica count) x (DB_POOL_SIZE + DB_MAX_OVERFLOW)` within the shared SQL Server's
  available capacity. The application lifespan also caps concurrent synchronous handlers with
  `THREAD_POOL_SIZE`.
- `docs/ARCHITECTURE.md` describes the target design, not deployed functionality. Use
  `README.md`, `CLAUDE.md`, and `docs/ROADMAP.md` for the current implementation and near-term
  scope.
