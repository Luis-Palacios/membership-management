from typing import Literal, Self

from pydantic import AnyUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from membership_management.env_file import ENV_FILE


class BaseDbSettings(BaseSettings):
    # Required, with no default, so a deployment that forgets it fails at startup instead of
    # silently running as "local" (which exposes /docs). validation_alias pins the env var name, so a
    # subclass's env_prefix doesn't turn it into e.g. MEMBERS_ENVIRONMENT: every DB shares one.
    environment: Literal["local", "staging", "production"] = Field(validation_alias="ENVIRONMENT")
    # Fails closed: a deployment that forgets DEBUG gets no tracebacks in responses, no DEBUG
    # logging and no SQL echo (which logs bound parameters).
    debug: bool = Field(default=False, validation_alias="DEBUG")

    @model_validator(mode="after")
    def reject_debug_in_production(self) -> Self:
        # Safe defaults only cover a *missing* DEBUG; this catches a wrong one, e.g. DEBUG=True
        # left in the task definition after an incident.
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be False when ENVIRONMENT is production")
        return self

    # See env_file.py for when .env is read. extra="ignore": ApiSettings and the other DB's settings
    # read the same .env, so each class sees the others' keys.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")


class PooledDbSettings(BaseDbSettings):
    """Connection URL, timeouts and pool sizing for one database.

    Each subclass sets its own env_prefix (e.g. "MEMBERS_"), so every field below is read from a
    prefixed env var (MEMBERS_DATABASE_URL, MEMBERS_DB_POOL_SIZE, ...) and each DB is tuned
    independently. How the two timeouts are applied is driver-specific; see each DB's database.py.
    """

    database_url: AnyUrl

    # Time to establish a new connection before giving up.
    db_connect_timeout_seconds: int = 5
    # Time a single query is allowed to run before the database aborts it.
    db_query_timeout_seconds: int = 30
    # Time a request waits for a free connection from the pool before raising.
    db_pool_timeout_seconds: int = 30
    # Max age of a pooled connection before it's discarded and reconnected, so we never hand out a
    # connection the server (or a NAT/load balancer in between) has silently dropped.
    db_pool_recycle_seconds: int = 1800

    # Connections kept open per process, even when idle. Total connections a single process can
    # open against this DB is db_pool_size + db_max_overflow. Once this runs as multiple
    # containers/replicas, multiply by (api workers x replica count) to get the real ceiling --
    # see the pool-sizing notes in .env.example.
    db_pool_size: int = 5
    # Extra connections allowed beyond db_pool_size under burst load; closed (not kept) once the
    # burst is over.
    db_max_overflow: int = 5
    # Ping a pooled connection with a trivial query before handing it out, so a connection the
    # server silently closed is replaced instead of failing the request that draws it.
    db_pool_pre_ping: bool = True
    # Hand out the most-recently-returned connection first (LIFO) instead of round-robin. Under
    # light/bursty load this keeps a small working set of connections warm and lets the rest
    # recycle or idle out sooner.
    db_pool_use_lifo: bool = True
