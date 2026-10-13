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
- Generate a members-database migration with
  `uv run alembic revision --autogenerate -m "short description"`, review the generated file in
  `src\membership_management\data\migrations\versions\`, then apply it with
  `uv run alembic upgrade head`. Verify it with `uv run alembic downgrade -1`, another
  `uv run alembic upgrade head`, and `uv run alembic check` (fails if models changed without a
  migration). `uv run alembic upgrade head --sql` previews the SQL without touching the database.
  Deployments, whose image has no `alembic.ini`, run `python -m membership_management.data.migrate`
  as a one-off task before the service update, never on app startup.

## Architecture

- This is a single membership-management microservice (membership applications, members, small
  groups and small-group reports) alongside an existing church application.
  Its current implementation is a synchronous SQL Server assimilation data layer consumed by a CLI
  and a FastAPI workspace member at `src/membership_management/api`. The API has its own
  `pyproject.toml`; keep FastAPI-specific dependencies and configuration there.
- Settings load from env vars and, outside staging/production, the root `.env`; start with
  `.env.example`. `ENVIRONMENT` is required, and `DEBUG` defaults to `False`. Importing the assimilation layer
  requires `ASSIMILATION_DATABASE_URL`; importing the members layer (including the API, which
  imports `data/models.py`) requires `MEMBERS_DATABASE_URL`. Never commit credentials.
- Both databases' settings subclass `PooledDbSettings` (`data/base_db_settings.py`) with their own
  `env_prefix`, so pool and timeout settings are per DB (`ASSIMILATION_DB_POOL_SIZE`,
  `MEMBERS_DB_POOL_SIZE`, ...); `ENVIRONMENT`/`DEBUG` are unprefixed via `validation_alias`. Engines
  come from `create_pooled_engine` (`data/pooled_engine.py`); each `database.py` passes only its
  driver-specific `connect_args`.
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
- The members database is this service's own PostgreSQL database (psycopg 3,
  `MEMBERS_DATABASE_URL`), separate from auth-server's. `data/database.py` owns its engine,
  `MembershipSessionLocal`, and `MemberManagementBase`, whose metadata has a constraint naming
  convention. Models live per domain in `data/<domain>/models/` (`members`, `small_groups`), are
  exported from that package's `__init__.py`, and every domain's `models` package is imported in the
  `data/models.py` registry.
- Alembic (`data/migrations/`, root `alembic.ini`, `script_location` is the package resource
  `membership_management.data:migrations`) owns the whole members database and only that database;
  never point it at the assimilation SQL Server database.
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
- Each Uvicorn worker has its own SQLAlchemy pool per database. Keep
  `(workers x replica count) x (ASSIMILATION_DB_POOL_SIZE + ASSIMILATION_DB_MAX_OVERFLOW)` within
  the shared SQL Server's available capacity, and the members equivalent, plus auth-server's pool,
  the migration task and admin tools, within the RDS instance's `max_connections`. Postgres
  timeouts are enforced server-side (`statement_timeout`, `idle_in_transaction_session_timeout`);
  migrations use `lock_timeout` and no statement timeout. The application lifespan also caps concurrent synchronous handlers with
  `THREAD_POOL_SIZE`.
- Never apply an autogenerated migration without reviewing it. A model missing from `data/models.py`
  makes autogenerate emit `drop_table` for its existing table; renames appear as drop + add; and
  changes to allowed values of VARCHAR + CHECK enums (e.g. `SmallGroupRole`) aren't detected and
  need a hand-written migration. Name indexes explicitly when the naming convention would mislead
  (e.g. partial unique indexes). Treat migrations that have run outside a developer machine as
  immutable, and keep each one compatible with the previously deployed code.
- Use `127.0.0.1`, not `localhost`, in local Postgres URLs: `localhost` resolves to `::1` first
  and hangs against Docker Desktop's Postgres.
- `docs/ARCHITECTURE.md` describes the target design, not deployed functionality. Use
  `README.md`, `CLAUDE.md`, and `docs/ROADMAP.md` for the current implementation and near-term
  scope.
