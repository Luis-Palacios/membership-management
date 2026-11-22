from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.claim_columns import ClaimColumns
from membership_management.data.database import MemberManagementBase


class OutboxEvent(ClaimColumns, MemberManagementBase):
    """Something that happened, written in the same transaction as the change itself, for the worker
    to act on later. Generic: no foreign keys (deleting a report must not cascade here; a consumer
    that finds its rows gone marks the event processed), payload is ids and facts only."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed', 'dead', 'expired')",
            name="status_valid",
        ),
        # 'processing' included: a lease that ran out (crashed worker) is found by the same scan.
        Index(
            "ix_outbox_events_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'failed', 'processing')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))  # report_conversation.comment_added
    schema_version: Mapped[int] = mapped_column(SmallInteger)
    aggregate_type: Mapped[str] = mapped_column(String(64))  # report_conversation
    aggregate_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Set by the writer (the comment's created_at), so the 24 h deadline counts from the comment.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
