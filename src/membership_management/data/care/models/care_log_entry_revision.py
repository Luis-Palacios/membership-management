from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Identity, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry import CareLogEntry


class CareLogEntryRevision(MemberManagementBase):
    """The text an entry had before an edit. Kept for pastoral accountability, never returned by the API."""

    __tablename__ = "care_log_entry_revisions"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("care_log_entries.id", ondelete="CASCADE"), index=True)
    # Null when the entry had no text yet (a plan with no purpose) and the edit gave it one.
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    entry: Mapped["CareLogEntry"] = relationship(back_populates="revisions")
