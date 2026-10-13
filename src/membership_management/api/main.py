import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

# Registers every members-DB model before any query runs: relationships between domains (e.g.
# SmallGroupMember -> Member) resolve classes by name, and fail with "expression 'Member' failed to
# locate a name" if a route only imported one side.
import membership_management.data.models  # noqa: F401
from membership_management.api.config import api_settings
from membership_management.api.logging_config import configure_logging
from membership_management.api.middleware import (
    RequestLoggingMiddleware,
    RequestTimeoutMiddleware,
)
from membership_management.api.routers import applications, members, people, small_groups
from membership_management.data.assimilation.config import settings
from membership_management.data.assimilation.database import engine
from membership_management.data.database import engine as members_engine

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # anyio's thread-pool limiter is per-event-loop, so it can only be set
    # from inside a running event loop -- this startup hook is that place.
    # Bounds concurrent sync (`def`) route handlers/dependencies; see the
    # thread_pool_size comment in config.py.
    anyio.to_thread.current_default_thread_limiter().total_tokens = api_settings.thread_pool_size
    yield
    # Release this process's pooled connections on shutdown (e.g. SIGTERM
    # during a container redeploy/scale-down) instead of relying on the OS
    # to close the sockets once the process exits.
    engine.dispose()
    members_engine.dispose()


app = FastAPI(
    title="Membership Management API",
    description="Church membership management: membership applications, members, small groups and reports",
    summary="API for church membership management",
    version="1.0.0",
    debug=settings.debug,
    docs_url="/docs" if settings.environment == "local" else None,
    redoc_url="/redoc" if settings.environment == "local" else None,
    openapi_url="/openapi.json" if settings.environment == "local" else None,
    lifespan=lifespan,
)
app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=api_settings.request_timeout_seconds)
if api_settings.cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.add_middleware(RequestLoggingMiddleware)
app.include_router(applications.router)
app.include_router(people.router)
app.include_router(members.router)
app.include_router(small_groups.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to the Membership Management API!"}


def _check_database(name: str, db_engine: Engine) -> dict[str, object]:
    pool = db_engine.pool
    # engine.pool is statically typed as the abstract Pool base, which doesn't declare
    # size()/checkedout()/overflow() -- those live on QueuePool. create_pooled_engine()
    # (pooled_engine.py) passes pool_size/max_overflow/pool_use_lifo/pool_timeout, which SQLAlchemy
    # only accepts for its default QueuePool (no poolclass override), so this is always QueuePool
    # at runtime.
    assert isinstance(pool, QueuePool)  # noqa: S101 -- type-narrowing only, not a security check
    # Pool stats for this process only -- with multiple workers/replicas, each process reports its
    # own pool, not a combined total. Read before the ping below checks out a connection, so they
    # don't count the health check itself. A reachable DB with an exhausted pool (checked_out near
    # size + overflow) needs a different response (raise that DB's *_DB_POOL_SIZE/_MAX_OVERFLOW,
    # add replicas) than a DB that's actually down, even though both can make requests queue
    # behind the pool timeout.
    pool_stats = {
        "size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check failed: %s database unreachable", name)
        return {"status": "unreachable", "pool": pool_stats}
    return {"status": "ok", "pool": pool_stats}


@app.get("/health")
def health_check(response: Response) -> dict[str, object]:
    # Each DB is pinged separately (not through a request session), so the body says *which* one is
    # down. Checked one after the other, so the worst case is about both connect timeouts combined
    # -- keep the load balancer's health-check timeout above that.
    databases = {
        "assimilation": _check_database("assimilation", engine),
        "members": _check_database("members", members_engine),
    }
    healthy = all(database["status"] == "ok" for database in databases.values())
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "unavailable", "databases": databases}
