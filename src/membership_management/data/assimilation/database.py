from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from .config import settings

ASSIMILATION_DATABASE_URL = str(settings.assimilation_database_url)

# Shared thread-safe connection pool engine
engine: Engine = create_engine(
    ASSIMILATION_DATABASE_URL,
    echo=settings.debug,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_use_lifo=settings.db_pool_use_lifo,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    # Always roll back a returned connection's transaction state before it's
    # reused, so a request that leaked an open transaction can never leave it
    # for the next request to inherit. This is a correctness invariant, not
    # an environment-dependent tradeoff, so unlike the settings above it's
    # not exposed as a env-configurable option.
    pool_reset_on_return="rollback",
    # pyodbc's login timeout: how long connecting to SQL Server may take.
    connect_args={"timeout": settings.db_connect_timeout_seconds},
)


@event.listens_for(engine, "connect")
def _set_query_timeout(
    dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
) -> None:
    # pyodbc's query timeout can only be set on an existing connection, not
    # passed to connect(), so it's set here for every new pooled connection.
    dbapi_connection.timeout = settings.db_query_timeout_seconds  # type: ignore[attr-defined]


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass
