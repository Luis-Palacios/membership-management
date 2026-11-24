from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Identity, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.care.models.care_log_entry import CareLogEntry
    from membership_management.data.guests.models import Guest
    from membership_management.data.members.models import Member


class CareLogEntryPerson(MemberManagementBase):
    """A person (member or guest) a care log entry is about; exactly one of `member_id`, `guest_id`."""

    __tablename__ = "care_log_entry_people"
    __table_args__ = (
        # NULLs are distinct in Postgres, so a guest's row never collides with a member's here.
        UniqueConstraint("entry_id", "member_id"),
        # Named: the convention's `uq` name uses only the first column, which the one above already took.
        UniqueConstraint("entry_id", "guest_id", name="uq_care_log_entry_people_entry_id_guest_id"),
        CheckConstraint("num_nonnulls(member_id, guest_id) = 1", name="one_person"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("care_log_entries.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), index=True)

    entry: Mapped["CareLogEntry"] = relationship(back_populates="people")
    member: Mapped["Member | None"] = relationship()
    guest: Mapped["Guest | None"] = relationship()
