from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry_note_revision import CareLogEntryNoteRevision
    from membership_management.data.members.models import Member


class CareLogEntryNote(MemberManagementBase):
    """One person's own account of an entry they took part in (care spec rules 59-63). On a done entry with
    participants, its author and each participant may write one. Seen by whoever sees the entry; a note never
    changes the entry. `author_user_id` is a JWT `sub` (no foreign key); `author_member_id` is who the note
    is shown under, and stays when that member is later removed from *With* (rule 61). Earlier texts are in
    `care_log_entry_note_revisions`, never returned; a delete is soft."""

    __tablename__ = "care_log_entry_notes"
    __table_args__ = (
        CheckConstraint("char_length(text) BETWEEN 1 AND 4000", name="text_length"),
        # One note per person (rule 59), among the notes not deleted: a deleted one can be written again.
        Index(
            "uq_care_log_entry_notes_entry_id_author_member_id",
            "entry_id",
            "author_member_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("care_log_entries.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[str] = mapped_column(String)
    author_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped["Member"] = relationship(foreign_keys=[author_member_id])
    revisions: Mapped[list["CareLogEntryNoteRevision"]] = relationship(
        back_populates="note", cascade="all, delete-orphan", passive_deletes=True
    )
