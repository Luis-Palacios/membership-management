from sqlalchemy import Engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from membership_management.data.pooled_engine import create_pooled_engine

from .config import settings

# Shared thread-safe connection pool engine
engine: Engine = create_pooled_engine(
    settings,
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
