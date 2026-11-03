from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member


class SmallGroupNoMeetingWeek(MemberManagementBase):
    """A church-wide no meeting: a whole week marked for every open group at once.

    Each group's no meeting is a normal report (held = false) pointing here through
    `SmallGroupReport.no_meeting_week_id`; this row is what edit reason and undo act on.
    """

    __tablename__ = "small_group_no_meeting_weeks"
    __table_args__ = (CheckConstraint("extract(dow from week_start) = 0", name="week_start_is_sunday"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    # Always a church Sunday (church_sunday()).
    week_start: Mapped[date] = mapped_column(Date, unique=True)
    # Copied into each linked report's not_held_reason.
    reason: Mapped[str | None] = mapped_column(String(255))
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set on edit reason.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    created_by: Mapped["Member"] = relationship()
