from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Identity, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry import CareLogEntry
    from membership_management.data.members.models import Member


class CareLogEntryParticipant(MemberManagementBase):
    """Staff who took part in an entry ("with whom", care spec rule 3). Display only: no access comes
    from it, except completing or cancelling a plan they are in. Members only."""

    __tablename__ = "care_log_entry_participants"
    __table_args__ = (UniqueConstraint("entry_id", "member_id"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("care_log_entries.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)

    entry: Mapped["CareLogEntry"] = relationship(back_populates="participants")
    member: Mapped["Member"] = relationship()
