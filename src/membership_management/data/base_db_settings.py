from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from membership_management.env_file import ENV_FILE


class BaseDbSettings(BaseSettings):
    # Required, with no default, so a deployment that forgets it fails at startup instead of
    # silently running as "local" (which exposes /docs).
    environment: Literal["local", "staging", "production"]
    # Fails closed: a deployment that forgets DEBUG gets no tracebacks in responses, no DEBUG
    # logging and no SQL echo (which logs bound parameters).
    debug: bool = False

    @model_validator(mode="after")
    def reject_debug_in_production(self) -> Self:
        # Safe defaults only cover a *missing* DEBUG; this catches a wrong one, e.g. DEBUG=True
        # left in the task definition after an incident.
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be False when ENVIRONMENT is production")
        return self

        # See env_file.py for when .env is read. extra="ignore": ApiSettings reads the same .env, so
        # each class sees the other's keys.
    
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")
