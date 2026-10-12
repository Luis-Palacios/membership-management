import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from membership_management.api.config import api_settings
from membership_management.api.dependencies import SessionDep
from membership_management.api.logging_config import configure_logging
from membership_management.api.middleware import (
    RequestLoggingMiddleware,
    RequestTimeoutMiddleware,
)
from membership_management.api.routers import applications, people
from membership_management.data.assimilation.config import settings
from membership_management.data.assimilation.database import engine

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
app.add_middleware(
    RequestTimeoutMiddleware, timeout_seconds=api_settings.request_timeout_seconds
)
if api_settings.cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
app.add_middleware(RequestLoggingMiddleware)
app.include_router(applications.router)
app.include_router(people.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to the Membership Management API!"}


@app.get("/health")
def health_check(db: SessionDep) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check failed: database unreachable")
        raise HTTPException(status_code=503, detail="Database unreachable")
    # Pool stats for this process only -- with multiple workers/replicas,
    # each process reports its own pool, not a combined total. A reachable
    # DB with an exhausted pool (checked_out near size + overflow) needs a
    # different response (raise db_pool_size/db_max_overflow, add replicas)
    # than a DB that's actually down, even though both can make requests
    # queue behind db_pool_timeout_seconds.
    pool = engine.pool
    # engine.pool is statically typed as the abstract Pool base, which doesn't declare
    # size()/checkedout()/overflow() -- those live on QueuePool. database.py's create_engine()
    # call passes pool_size/max_overflow/pool_use_lifo/pool_timeout, which SQLAlchemy only
    # accepts for its default QueuePool (no poolclass override), so this is always QueuePool
    # at runtime.
    assert isinstance(pool, QueuePool)  # noqa: S101 -- type-narrowing only, not a security check

    return {
        "status": "ok",
        "db_pool": {
            "size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        },
    }
