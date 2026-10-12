from typing import Literal, Self

from pydantic import AnyUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from membership_management.env_file import ENV_FILE


class Settings(BaseSettings):
    # Required, with no default, so a deployment that forgets it fails at startup instead of
    # silently running as "local" (which exposes /docs).
    environment: Literal["local", "staging", "production"]
    # Fails closed: a deployment that forgets DEBUG gets no tracebacks in responses, no DEBUG
    # logging and no SQL echo (which logs bound parameters).
    debug: bool = False

    assimilation_database_url: AnyUrl

    # Time to establish a new connection to SQL Server before giving up.
    db_connect_timeout_seconds: int = 5
    # Time a single query is allowed to run before SQL Server aborts it.
    db_query_timeout_seconds: int = 30
    # Time a request waits for a free connection from the pool before raising.
    db_pool_timeout_seconds: int = 30
    # Max age of a pooled connection before it's discarded and reconnected,
    # so we never hand out a connection SQL Server has silently dropped.
    db_pool_recycle_seconds: int = 1800

    # Connections kept open per process, even when idle. Total connections a
    # single process can open against SQL Server is db_pool_size +
    # db_max_overflow. Once this runs as multiple containers/replicas,
    # multiply by (api workers x replica count) to get the real ceiling
    # against SQL Server -- see WORKERS in the api package's .env.example.
    db_pool_size: int = 5
    # Extra connections allowed beyond db_pool_size under burst load; closed
    # (not kept) once the burst is over.
    db_max_overflow: int = 5
    # Ping a pooled connection with a trivial query before handing it out, so
    # a connection SQL Server silently closed is replaced instead of failing
    # the request that draws it.
    db_pool_pre_ping: bool = True
    # Hand out the most-recently-returned connection first (LIFO) instead of
    # round-robin. Under light/bursty load this keeps a small working set of
    # connections warm and lets the rest recycle or idle out sooner.
    db_pool_use_lifo: bool = True

    # See env_file.py for when .env is read. extra="ignore": ApiSettings reads the same .env, so
    # each class sees the other's keys.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def reject_debug_in_production(self) -> Self:
        # Safe defaults only cover a *missing* DEBUG; this catches a wrong one, e.g. DEBUG=True
        # left in the task definition after an incident.
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be False when ENVIRONMENT is production")
        return self


settings = Settings()
