"""Generic deliveries: a domain hands over `NotificationRequest`s, this applies the recipients' channel
preferences and stores what is left. Knows categories, channels and templates, never conversations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.notifications.models import NotificationDelivery, NotificationPreference


@dataclass(frozen=True)
class NotificationRequest:
    """One message a domain wants sent. `payload` is exactly what the Sender sends (minus the
    idempotency key, which comes from the delivery id); `not_after` is the domain's deadline."""

    recipient_user_id: str
    category: str
    channel: str
    template: str
    payload: Mapping[str, Any]
    not_after: datetime


def create_deliveries(session: Session, source_event_id: int, requests: Sequence[NotificationRequest]) -> int:
    """Store the requests whose recipient hasn't turned their (category, channel) off. Inside the
    event's transaction; a retried event inserts nothing twice (unique per event, user, channel).
    Returns how many rows were inserted."""
    if not requests:
        return 0
    pref = NotificationPreference
    off = {
        (user_id, category, channel)
        for user_id, category, channel in session.execute(
            select(pref.user_id, pref.category, pref.channel).where(
                pref.user_id.in_({r.recipient_user_id for r in requests}),
                pref.enabled.is_(False),
            )
        )
    }
    rows = [
        {
            "source_event_id": source_event_id,
            "recipient_user_id": r.recipient_user_id,
            "category": r.category,
            "channel": r.channel,
            "template": r.template,
            "payload": dict(r.payload),
            "next_attempt_at": func.now(),
            "expires_at": r.not_after,
        }
        for r in requests
        if (r.recipient_user_id, r.category, r.channel) not in off
    ]
    if not rows:
        return 0
    inserted = session.execute(
        insert(NotificationDelivery)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["source_event_id", "recipient_user_id", "channel"])
        .returning(NotificationDelivery.id)
    )
    return len(inserted.all())


def is_enabled(session: Session, user_id: str, category: str, channel: str) -> bool:
    """The re-check right before sending: off now → the delivery ends `suppressed`. No row = enabled."""
    enabled = session.scalar(
        select(NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
            NotificationPreference.channel == channel,
        )
    )
    return enabled is not False
