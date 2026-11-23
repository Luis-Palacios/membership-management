from datetime import datetime
from typing import Any

from pydantic import ConfigDict, field_validator
from pydantic.json_schema import SkipJsonSchema

from membership_management.api.schemas.base import CamelModel


class EmailSwitchesSchema(CamelModel):
    """One value per kind of email (report-submitted-emails rule 9)."""

    # "Conversations": leaders' and elders' comments (category report_conversation).
    report_conversation: bool
    # "Submitted reports": a report submitted in a watched group (category report_submitted).
    report_submitted: bool
    # "Weekly report reminders": the weekly nudge to a leader whose group hasn't submitted (category
    # report_reminder). Independent of Watching (report-reminder-emails rule 14).
    report_reminder: bool


class NotificationPreferencesSchema(CamelModel):
    # The caller's switches (default on: no stored row = enabled).
    email: EmailSwitchesSchema
    # The server's kill switch per kind (CONVERSATION_EMAILS_ENABLED, REPORT_SUBMITTED_EMAILS_ENABLED,
    # REPORT_REMINDER_EMAILS_ENABLED): staff-app hides a switch while its value is false, and the
    # Watching switches while both of the first two are.
    available: EmailSwitchesSchema


class EmailSwitchesUpdateSchema(CamelModel):
    """Any subset; a key left out keeps its value. null and unknown keys are 422."""

    model_config = ConfigDict(extra="forbid")

    report_conversation: bool | SkipJsonSchema[None] = None
    report_submitted: bool | SkipJsonSchema[None] = None
    report_reminder: bool | SkipJsonSchema[None] = None

    @field_validator("report_conversation", "report_submitted", "report_reminder", mode="after")
    @classmethod
    def not_null(cls, value: bool | None) -> bool:
        # Defaults aren't validated, so this only sees a value that was sent.
        if value is None:
            raise ValueError("must be true or false")
        return value


class NotificationPreferencesUpdateSchema(CamelModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailSwitchesUpdateSchema


class WatchedGroupSchema(CamelModel):
    small_group_id: int
    name: str
    closed: bool
    watching: bool


class WatchedGroupsSchema(CamelModel):
    items: list[WatchedGroupSchema]


class WatchUpdateSchema(CamelModel):
    watching: bool


class WatchSchema(CamelModel):
    small_group_id: int
    watching: bool


class NotificationSchema(CamelModel):
    """One entry of the in-app list (notifications spec, rule 1). `template` + `data` are the email's;
    staff-app renders its own text from them and skips a template it doesn't know."""

    id: int
    category: str
    template: str
    data: dict[str, Any]
    path: str
    created_at: datetime
    read_at: datetime | None


class NotificationsPageSchema(CamelModel):
    items: list[NotificationSchema]
    # The id to send as `before` for the next page; null on the last one.
    next_before: int | None


class UnreadCountSchema(CamelModel):
    # IN_APP_NOTIFICATIONS_ENABLED: false hides the bell (and `unread` is 0).
    enabled: bool
    unread: int


class NotificationOpenedSchema(CamelModel):
    path: str


class NotificationsMarkedSchema(CamelModel):
    marked: int
