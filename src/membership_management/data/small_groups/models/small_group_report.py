from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.report_conversation import ReportConversation
    from membership_management.data.small_groups.models.small_group import SmallGroup
    from membership_management.data.small_groups.models.small_group_report_attendance import (
        SmallGroupReportAttendance,
    )
    from membership_management.data.small_groups.models.small_group_report_item import SmallGroupReportItem


class SmallGroupReport(MemberManagementBase):
    __tablename__ = "small_group_reports"
    __table_args__ = (
        UniqueConstraint("small_group_id", "meeting_date"),
        CheckConstraint("NOT held OR not_held_reason IS NULL", name="not_held_reason_only_when_not_held"),
        CheckConstraint("held OR address IS NULL", name="not_held_has_no_texts"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    small_group_id: Mapped[int] = mapped_column(ForeignKey("small_groups.id"), index=True)
    meeting_date: Mapped[date] = mapped_column(Date)
    # False = the group didn't meet on meeting_date (a "no meeting"). It still occupies the date, so
    # the date isn't "not filed"; it has no attendance and no group texts.
    held: Mapped[bool] = mapped_column(Boolean, server_default=true())
    not_held_reason: Mapped[str | None] = mapped_column(String(255))
    # Normally the same address from the small group but could vary for this particular meeting.
    address: Mapped[str | None] = mapped_column(String(255))

    # The leader or co-leader who filled in this report, including every attendance row.
    # The service layer checks they held one of those roles on meeting_date; the DB can't.
    submitted_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    small_group: Mapped["SmallGroup"] = relationship()
    submitted_by: Mapped["Member"] = relationship()
    attendances: Mapped[list["SmallGroupReportAttendance"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    # Deleting a report deletes its conversations: the database cascades (ON DELETE CASCADE).
    conversations: Mapped[list["ReportConversation"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )
    # Deleting a report deletes its items: the database cascades (ON DELETE CASCADE).
    items: Mapped[list["SmallGroupReportItem"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )
