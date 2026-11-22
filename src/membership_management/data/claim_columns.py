import uuid
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class ClaimColumns:
    """The lease columns shared by outbox_events and notification_deliveries (report conversations
    spec, *Claim columns*). Each table adds its own `status` CHECK and its partial due-index."""

    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    # Claims that ended in a crash, hang or exception: the poison counter (cap 5). Counted at claim
    # time, and given back on a transient failure.
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    # Recorded failures of any kind: drives the backoff (1, 5, 15, 60 min, then hourly).
    failures: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # New uuid per claim; every later write is fenced on it.
    claim_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # created_at + 24 h for events; deliveries inherit their event's.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Status code, error `code` or exception class. Never PII.
    last_error: Mapped[str | None] = mapped_column(String(200))
