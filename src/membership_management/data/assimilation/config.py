from pydantic_settings import SettingsConfigDict

from membership_management.data.base_db_settings import PooledDbSettings


class Settings(PooledDbSettings):
    # Every pool/timeout field is read as ASSIMILATION_<NAME> (ASSIMILATION_DATABASE_URL,
    # ASSIMILATION_DB_POOL_SIZE, ...). This DB is shared with the existing church web app, so keep
    # its pool ceiling well under the headroom SQL Server actually has left -- see .env.example.
    model_config = SettingsConfigDict(env_prefix="ASSIMILATION_")


settings = Settings()
