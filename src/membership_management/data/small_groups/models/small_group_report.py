from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Identity, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.small_group import SmallGroup
    from membership_management.data.small_groups.models.small_group_report_attendance import (
        SmallGroupReportAttendance,
    )


class SmallGroupReport(MemberManagementBase):
    __tablename__ = "small_group_reports"
    __table_args__ = (UniqueConstraint("small_group_id", "meeting_date"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    small_group_id: Mapped[int] = mapped_column(ForeignKey("small_groups.id"), index=True)
    meeting_date: Mapped[date] = mapped_column(Date)
    # Normally the same address from the small group but could vary for this particular meeting.
    address: Mapped[str | None] = mapped_column(String(255))
    group_prayer_request: Mapped[str | None] = mapped_column(String(1024))
    group_praise_report: Mapped[str | None] = mapped_column(String(1024))

    # Discussion points relevant to the group that were raised during the meeting.
    # Elders may follow up on these in subsequent meetings.
    group_relevant_discussion: Mapped[str | None] = mapped_column(String(1024))

    # The leader or co-leader who filled in this report, including every attendance row.
    # The service layer checks they held one of those roles on meeting_date; the DB can't.
    submitted_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    small_group: Mapped["SmallGroup"] = relationship()
    submitted_by: Mapped["Member"] = relationship()
    attendances: Mapped[list["SmallGroupReportAttendance"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
