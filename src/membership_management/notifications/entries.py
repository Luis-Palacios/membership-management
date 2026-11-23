"""Generic in-app entries: a domain hands over `EntryRequest`s, this stores them as the recipients' list
(notifications spec, rule 1). Knows categories and templates, never conversations.

Unlike `create_deliveries` there is no preference filter (rule 2): everyone the domain decided on gets
the entry, before any channel's switch is applied.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.notifications.models import UserNotification


@dataclass(frozen=True)
class EntryRequest:
    """One entry a domain wants in one person's list. `template`, `data` and `path` are exactly the
    email's. `small_group_ids` is for reminder entries only (rule 14)."""

    user_id: str
    category: str
    template: str
    data: Mapping[str, Any]
    path: str
    subject_key: str
    small_group_ids: Sequence[int] | None = None


def create_entries(session: Session, source_event_id: int, requests: Sequence[EntryRequest]) -> int:
    """Store the entries, inside the event's transaction. A retried event inserts nothing twice (unique
    per event and user). Returns how many rows were inserted."""
    if not requests:
        return 0
    rows = [
        {
            "user_id": r.user_id,
            "source_event_id": source_event_id,
            "category": r.category,
            "template": r.template,
            "data": dict(r.data),
            "path": r.path,
            "subject_key": r.subject_key,
            "small_group_ids": list(r.small_group_ids) if r.small_group_ids is not None else None,
        }
        for r in requests
    ]
    inserted = session.execute(
        insert(UserNotification)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["source_event_id", "user_id"])
        .returning(UserNotification.id)
    )
    return len(inserted.all())
