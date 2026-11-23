from datetime import time
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from membership_management.env_file import ENV_FILE


class NotificationSettings(BaseSettings):
    """What the worker and the comment transaction need to know about emails. Kept out of
    `ApiSettings` so the worker (`python -m membership_management.worker`) never imports the API
    package. Reads the same env var names as the API, so one value configures both."""

    # Same .env handling as the data layer's Settings (see env_file.py).
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "staging", "production"] = Field(validation_alias="ENVIRONMENT")

    # Kill switches, one per kind of email. Off: that kind writes no outbox rows (so its emails and
    # its fast path never happen). With all three off (these two and the reminder below): no worker
    # and no calls to auth-server at all.
    conversation_emails_enabled: bool = False
    report_submitted_emails_enabled: bool = False
    # Weekly reminder to leaders whose group hasn't submitted this week's report. Off: the worker
    # never triggers it, and staff-app hides the switch.
    report_reminder_emails_enabled: bool = False

    # The reminder's schedule, one per deployment for now (report-reminder-emails spec, rule 1).
    # Same CHURCH_TIMEZONE as ApiSettings, read here too so the worker never imports the api package.
    church_timezone: str = "America/Managua"
    # ISO weekday, 1 (Monday) to 7 (Sunday), like Weekday; 6 = Saturday.
    report_reminder_day: int = 6
    # HH:MM, 24-hour, local time in church_timezone.
    report_reminder_time: time = time(8, 0)

    # Same AUTH_SERVER_URL as ApiSettings: auth-server's origin as this service reaches it, no
    # trailing slash. The /internal/* calls go there.
    auth_server_url: str

    # Same INTERNAL_API_TOKEN as ApiSettings, sent as X-Internal-Token on every /internal/* call.
    internal_api_token: SecretStr | None = None

    @model_validator(mode="after")
    def require_token_when_enabled(self) -> Self:
        # Every environment, local too: without the token auth-server answers 503
        # internal_api_disabled, so every email would retry for 24 h and expire unnoticed.
        token = self.internal_api_token.get_secret_value() if self.internal_api_token else ""
        if token.strip():
            return self
        if self.conversation_emails_enabled:
            raise ValueError("CONVERSATION_EMAILS_ENABLED needs INTERNAL_API_TOKEN")
        if self.report_submitted_emails_enabled:
            raise ValueError("REPORT_SUBMITTED_EMAILS_ENABLED needs INTERNAL_API_TOKEN")
        if self.report_reminder_emails_enabled:
            raise ValueError("REPORT_REMINDER_EMAILS_ENABLED needs INTERNAL_API_TOKEN")
        return self

    @property
    def any_emails_enabled(self) -> bool:
        """Whether the worker has anything to do: it runs (embedded or on its own) while any is on."""
        return (
            self.conversation_emails_enabled
            or self.report_submitted_emails_enabled
            or self.report_reminder_emails_enabled
        )

    @field_validator("church_timezone", mode="after")
    @classmethod
    def validate_church_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"CHURCH_TIMEZONE {value!r} is not a valid IANA timezone") from exc
        return value

    @field_validator("report_reminder_day", mode="after")
    @classmethod
    def validate_reminder_day(cls, value: int) -> int:
        if not 1 <= value <= 7:
            raise ValueError("REPORT_REMINDER_DAY must be 1 (Monday) to 7 (Sunday)")
        return value

    @field_validator("report_reminder_time", mode="after")
    @classmethod
    def validate_reminder_time(cls, value: time) -> time:
        # Local church time, so an offset would contradict CHURCH_TIMEZONE.
        if value.tzinfo is not None:
            raise ValueError("REPORT_REMINDER_TIME is local time (HH:MM), without a UTC offset")
        return value

    @field_validator("auth_server_url", mode="after")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


notification_settings = NotificationSettings()
