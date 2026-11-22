from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.claim_columns import ClaimColumns
from membership_management.data.database import MemberManagementBase


class NotificationDelivery(ClaimColumns, MemberManagementBase):
    """One message to one user on one channel, created from an outbox event. `payload` is exactly
    what the Sender sends and never changes after insert (the idempotency key
    `mm:notification-delivery:{id}` must always carry the same body). Generic: knows categories and
    templates, not conversations."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        # A retried event can't create a second delivery for the same person and channel.
        UniqueConstraint("source_event_id", "recipient_user_id", "channel"),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'dead', 'expired', 'suppressed')",
            name="status_valid",
        ),
        # 'sending' included: a lease that ran out (crashed worker) is found by the same scan.
        Index(
            "ix_notification_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'failed', 'sending')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # No FK: events are purged after 30 days, deliveries kept 90.
    source_event_id: Mapped[int] = mapped_column(BigInteger)
    recipient_user_id: Mapped[str] = mapped_column(String)  # auth-server user id, no FK
    category: Mapped[str] = mapped_column(String(32))  # report_conversation
    channel: Mapped[str] = mapped_column(String(16))  # email
    template: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
