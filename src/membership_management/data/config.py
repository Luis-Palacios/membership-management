from pydantic_settings import SettingsConfigDict

from membership_management.data.base_db_settings import PooledDbSettings


class Settings(PooledDbSettings):
    # Every field is read as MEMBERS_<NAME> (MEMBERS_DATABASE_URL, MEMBERS_DB_POOL_SIZE, ...).
    model_config = SettingsConfigDict(env_prefix="MEMBERS_")

    # Postgres ends a session that opened a transaction and then sat idle this long, releasing its
    # locks. pool_reset_on_return only cleans up connections that make it back to the pool; this
    # also covers ones that never do (a hung request, a killed worker).
    db_idle_in_transaction_timeout_seconds: int = 60

    # Migrations only: how long a DDL statement waits for a table lock before failing. A waiting
    # ALTER TABLE blocks every query queued behind it, so without this one slow query can stall the
    # whole API for as long as the migration waits. Failing fast lets the migration be retried.
    migration_lock_timeout_seconds: int = 5


settings = Settings()
