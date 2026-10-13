from datetime import date
from enum import IntEnum

from sqlalchemy import CheckConstraint, Date, Identity, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class Weekday(IntEnum):
    """ISO weekday numbers, matching date.isoweekday()."""

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class SmallGroup(MemberManagementBase):
    __tablename__ = "small_groups"
    __table_args__ = (CheckConstraint("meeting_day BETWEEN 1 AND 7", name="meeting_day_valid"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    meeting_address: Mapped[str | None] = mapped_column(String(255))
    # ISO weekday (1=Monday .. 7=Sunday, see Weekday) the group usually meets; null if unset.
    # Used to prefill report dates and schedule reminders. Reports store their own actual meeting
    # date, so changing this never rewrites history.
    meeting_day: Mapped[int | None] = mapped_column(SmallInteger)

    # Groups are closed, never deleted, so their membership and leadership history survives
    # (small_group_members' foreign key blocks deleting a group that has any history).
    # Leaders are small_group_members rows with role "leader"/"co_leader", not a column here.
    closed_at: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"<SmallGroup(id={self.id}, name={self.name})>"
