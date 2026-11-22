from membership_management.api.schemas.base import CamelModel


class NotificationPreferencesSchema(CamelModel):
    # The caller's "Conversation emails" switch (default on).
    conversation_emails: bool
    # The server's kill switch (CONVERSATION_EMAILS_ENABLED): staff-app hides the email and Watching
    # switches while it's off.
    emails_enabled: bool


class NotificationPreferencesUpdateSchema(CamelModel):
    conversation_emails: bool


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
