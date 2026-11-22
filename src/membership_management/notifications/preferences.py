"""A user's channel preference per category (generic). No row = enabled; `deliveries.is_enabled` reads it."""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.notifications.models import NotificationPreference
from membership_management.notifications.deliveries import is_enabled

__all__ = ["is_enabled", "set_enabled"]


def set_enabled(session: Session, user_id: str, category: str, channel: str, *, enabled: bool) -> None:
    """Upsert, also when turning it back on (the row keeps `updated_at` as the last change). Committed
    here; turning it off also stops what is already queued (re-checked right before each send)."""
    statement = insert(NotificationPreference).values(
        user_id=user_id, category=category, channel=channel, enabled=enabled, updated_at=func.now()
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "category", "channel"],
            set_={"enabled": statement.excluded.enabled, "updated_at": statement.excluded.updated_at},
        )
    )
    session.commit()
