"""The push channel's requests (notifications spec, rules 1 and 5, *Contracts (Part 2: push)*). A domain
that decided its recipients once builds the email requests and the in-app entries; this turns the email
requests into push ones: same recipient, template, data and path, plus the three envelope fields. Generic:
knows channels and templates, never conversations. Which kinds send push (rule 3) is the caller's gate,
`notification_settings.push_enabled_for`."""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from membership_management.notifications.deliveries import NotificationRequest
from membership_management.notifications.entries import EntryResult

PUSH_CHANNEL = "push"


def push_requests(
    requests: Sequence[NotificationRequest], entries: Mapping[str, EntryResult]
) -> list[NotificationRequest]:
    """One `channel = "push"` request per email request. `entries` is what `create_entries` returned for
    the same event: a recipient with an entry gets its id as `notificationId` and their unread count
    (that entry included) as `badgeCount`. With in-app off there are no entries: `notificationId` is null
    and `badgeCount` 0 (nothing is unread, since nothing is kept). The preference filter in
    `create_deliveries` later drops the push of whoever turned push off for that category."""
    out = []
    for request in requests:
        entry = entries.get(request.recipient_user_id)
        payload = {
            **request.payload,
            "channel": PUSH_CHANNEL,
            "notificationId": entry.notification_id if entry is not None else None,
            "badgeCount": entry.unread if entry is not None else 0,
        }
        out.append(replace(request, channel=PUSH_CHANNEL, payload=payload))
    return out
