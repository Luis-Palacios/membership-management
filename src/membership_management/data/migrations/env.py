from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

import membership_management.data.models  # noqa: F401  (registers every table on the metadata)
from membership_management.data.config import settings
from membership_management.data.database import MemberManagementBase

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MemberManagementBase.metadata
DATABASE_URL = str(settings.database_url)

# Any fixed number works; it only has to be the same for every migrate run against this database
# (advisory locks are per database, so auth-server's own key never meets this one).
MIGRATION_LOCK_KEY = 41_552_018

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            # statement_timeout=0: unlike API requests, a data backfill may legitimately run long.
            # lock_timeout is set below, after the advisory lock, not here.
            "options": "-c statement_timeout=0",
        },
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            # Wait for any other migrate run to finish, so a second run applies nothing and exits 0
            # instead of failing on the first run's tables. The xact lock is released at commit or
            # rollback. It comes before run_migrations(), which reads the current revision only
            # once the lock is held.
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
            # Fail fast instead of queueing behind a slow query while every query after it queues
            # behind this migration (see migration_lock_timeout_seconds in config.py). Set after the
            # advisory lock, because lock_timeout applies to advisory locks too and would turn the
            # wait above into an error. SET LOCAL ends with the transaction.
            lock_timeout_ms = settings.migration_lock_timeout_seconds * 1000
            connection.execute(text(f"SET LOCAL lock_timeout = {lock_timeout_ms}"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
