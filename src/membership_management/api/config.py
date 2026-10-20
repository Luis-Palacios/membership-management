from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from membership_management.env_file import ENV_FILE


class ApiSettings(BaseSettings):
    # Browser origins allowed to call this API cross-origin. Empty (the default) means the CORS
    # middleware isn't mounted: no browser calls this API today -- staff-app calls it server-side
    # with a JWT, and /docs is same-origin. Set it only for a browser client on another origin.
    cors_allowed_origins: Annotated[list[str], NoDecode] = []

    # Bare origin of auth-server as *this service* reaches it, e.g. "http://localhost:5000" locally
    # or "http://auth-server:5000" over ECS Service Connect -- no trailing slash, no /api/auth
    # suffix. Only used to build the JWKS URL (auth_server_url + "/api/auth/.well-known/jwks.json");
    # it is a network address, not an identity, so it says nothing about what's inside a token.
    auth_server_url: str

    # Expected `iss` and `aud` claims on every verified JWT. better-auth derives both from
    # new URL(BETTER_AUTH_URL).origin, which JS never renders with a trailing slash (verified by
    # reading better-auth's context/create-context.mjs) -- so these must equal auth-server's
    # BETTER_AUTH_URL origin *exactly*, i.e. the PUBLIC url (https://staff.example.org in prod),
    # which differs from auth_server_url once the fetch goes over an internal address. All three
    # are kept as plain str rather than pydantic's AnyUrl, since AnyUrl normalizes a bare origin
    # by *adding* a trailing slash, which would silently break every iss/aud comparison.
    jwt_issuer: str
    jwt_audience: str

    # Same required ENVIRONMENT the data layer reads (see BaseDbSettings), repeated here only so
    # internal_api_token can be required outside local.
    environment: Literal["local", "staging", "production"] = Field(validation_alias="ENVIRONMENT")

    # Shared secret auth-server sends as X-Internal-Token to the internal endpoints (service to
    # service; the JWT only covers browser sessions). Required in staging/production; unset locally,
    # where /internal/* is disabled and answers 404.
    internal_api_token: SecretStr | None = None

    # Port the production server (run.py) binds to.
    port: int = 8000

    # Uvicorn worker processes for run.py. Each worker is a separate process
    # with its own SQLAlchemy engine/pool per DB, so total connections to each
    # DB become workers x (that DB's db_pool_size + db_max_overflow) -- and multiply again by
    # replica count once this runs as multiple containers. Each worker also
    # gets its own in-memory rate-limiter counters -- see the warning in
    # rate_limit.py -- so a "10/minute" limit effectively becomes
    # "10 x workers per minute", silently, with no error to signal it.
    # Once deployed behind an orchestrator (ECS/K8s), prefer scaling via
    # replica count and leave this at 1 -- the orchestrator can health-check
    # and restart a replica independently, which uvicorn's own multi-worker
    # mode doesn't do as robustly.
    workers: int = 1

    # Wall-clock cap on handling a single request, regardless of what's slow
    # inside it (e.g. a hung DB call). Enforced by RequestTimeoutMiddleware.
    request_timeout_seconds: float = 30
    # How long an idle keep-alive connection stays open between requests.
    keep_alive_timeout_seconds: int = 5
    # How long in-flight requests get to finish when the server receives
    # SIGTERM (e.g. `docker stop`) before it's killed outright.
    graceful_shutdown_timeout_seconds: int = 30

    # Default rate limit in `limits` syntax (e.g. "300/minute"), applied per authenticated user
    # (verified JWT `sub`) across all routes -- see rate_limit.py. With the in-memory store and
    # workers/replicas above 1 this becomes "<value> x (workers x replicas)" in practice,
    # silently; see rate_limit_storage_uri below.
    default_rate_limit: str = "300/minute"

    # Where rate-limit counters live, as a `limits` storage URI. "memory://" keeps them in this
    # process only (fine at 1 worker / 1 replica -- see the caveat in rate_limit.py). For more than
    # one worker or replica, point every instance at one shared store instead, e.g.
    # "redis://<host>:6379" (ElastiCache on AWS), or the counters silently multiply by
    # workers x replicas. Redis also needs the extra installed: `limits[redis]`.
    rate_limit_storage_uri: str = "memory://"

    # Max simultaneous connections uvicorn will accept before returning 503
    # to new ones. None means unlimited (uvicorn's own default). This caps
    # concurrency at the server level, independent of the DB pool -- useful
    # to fail fast under overload instead of queuing everything behind
    # db_pool_timeout_seconds.
    limit_concurrency: int | None = None
    # Max pending TCP connections the OS will queue once limit_concurrency
    # (or worker capacity) is saturated, before refusing new ones outright.
    # 2048 matches uvicorn's own default.
    backlog: int = 2048

    # Max sync (`def`, not `async def`) route handlers -- and sync
    # dependencies -- allowed to run concurrently per process. FastAPI runs
    # these on anyio's default thread pool, not the asyncio event loop
    # (async def routes bypass this entirely). 40 matches anyio's own
    # default. Per process, same as db_pool_size/db_max_overflow -- multiply
    # by workers x replicas for the real total. If this is smaller than a
    # DB's db_pool_size + db_max_overflow, *this* becomes the binding concurrency
    # limit for sync routes using that DB instead of its pool; if it's
    # larger, the DB pool stays the bottleneck and raising this further has
    # no effect. Applied in main.py's lifespan startup hook (not passed to
    # uvicorn), so unlike limit_concurrency/backlog/workers this one *does*
    # take effect under `fastapi dev` too, not just run.py.
    thread_pool_size: int = 40

    # IANA timezone of the church, used for every date-only business "today" (a member joining or
    # leaving a small group, a group closing). The server clock is UTC, so without this "today"
    # flips to tomorrow at 6 pm in Managua. One timezone per deployment for now; once
    # multi-tenancy lands this moves onto the church/ministry. Validated at startup.
    church_timezone: str = "America/Managua"

    # Same .env handling as the data layer's Settings (see env_file.py).
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def require_internal_api_token_outside_local(self) -> Self:
        token = self.internal_api_token.get_secret_value() if self.internal_api_token else ""
        if self.environment != "local" and not token:
            raise ValueError("INTERNAL_API_TOKEN is required when ENVIRONMENT is staging or production")
        return self

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("church_timezone", mode="after")
    @classmethod
    def validate_church_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}; use an IANA name like America/Managua") from exc
        return value

    @field_validator("auth_server_url", "jwt_issuer", "jwt_audience", mode="after")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


api_settings = ApiSettings()
