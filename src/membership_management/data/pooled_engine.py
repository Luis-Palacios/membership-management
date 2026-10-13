from collections.abc import Mapping

from sqlalchemy import Engine, create_engine

from membership_management.data.base_db_settings import PooledDbSettings


def create_pooled_engine(settings: PooledDbSettings, *, connect_args: Mapping[str, object]) -> Engine:
    """A QueuePool engine sized and tuned from settings.

    The pool options are SQLAlchemy's and work the same for every database. connect_args is the
    driver-specific part (each driver names its connect/query timeouts differently), so each DB's
    database.py passes its own.
    """
    return create_engine(
        str(settings.database_url),
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_use_lifo=settings.db_pool_use_lifo,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        # Always roll back a returned connection's transaction state before it's reused, so a
        # request that leaked an open transaction can never leave it for the next request to
        # inherit. This is a correctness invariant, not an environment-dependent tradeoff, so unlike
        # the settings above it's not exposed as an env-configurable option.
        pool_reset_on_return="rollback",
        connect_args=dict(connect_args),
    )
