from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Identity, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry_note import CareLogEntryNote


class CareLogEntryNoteRevision(MemberManagementBase):
    """The text a note had before an edit. Kept for pastoral accountability, never returned by the API."""

    __tablename__ = "care_log_entry_note_revisions"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("care_log_entry_notes.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    note: Mapped["CareLogEntryNote"] = relationship(back_populates="revisions")
