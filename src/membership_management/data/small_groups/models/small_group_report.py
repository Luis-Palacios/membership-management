from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
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
    from membership_management.data.small_groups.models.small_group_no_meeting_week import (
        SmallGroupNoMeetingWeek,
    )
    from membership_management.data.small_groups.models.small_group_report_attendance import (
        SmallGroupReportAttendance,
    )
    from membership_management.data.small_groups.models.small_group_report_item import SmallGroupReportItem


class ReportStatus(StrEnum):
    """A draft is saved as it is filled in and seen only by the group's leaders and whoever started it;
    submitting is one-way (report auto-save rules 1, 5 and 14)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"


class SmallGroupReport(MemberManagementBase):
    __tablename__ = "small_group_reports"
    __table_args__ = (
        UniqueConstraint("small_group_id", "meeting_date"),
        CheckConstraint("NOT held OR not_held_reason IS NULL", name="not_held_reason_only_when_not_held"),
        CheckConstraint("held OR address IS NULL", name="not_held_has_no_texts"),
        CheckConstraint("NOT held OR no_meeting_week_id IS NULL", name="no_meeting_week_only_when_not_held"),
        CheckConstraint("status IN ('draft', 'submitted')", name="status_valid"),
        CheckConstraint(
            "(status = 'draft') = (submitted_by_member_id IS NULL)", name="submitted_by_unless_draft"
        ),
        CheckConstraint("(status = 'draft') = (submitted_at IS NULL)", name="submitted_at_unless_draft"),
        CheckConstraint("held OR status = 'submitted'", name="no_meeting_never_draft"),
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

    status: Mapped[ReportStatus] = mapped_column(Text, server_default=ReportStatus.SUBMITTED.value)
    # +1 on every write: a save or submit based on an older version is refused (auto-save rule 9).
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    # Who first saved the report, and when. Backfilled from the submitter for older reports.
    started_by_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The last save after the first one; the member is None for an unlinked admin.
    last_edited_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The leader or co-leader who submitted this report, including every attendance row; both null
    # while it is a draft. The service layer checks they held one of those roles on meeting_date; the
    # DB can't.
    submitted_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a church-wide no meeting created this report; cleared when a leader edits its reason
    # or date. Undo deletes the reports still linked explicitly, so no ORM cascade.
    no_meeting_week_id: Mapped[int | None] = mapped_column(
        ForeignKey("small_group_no_meeting_weeks.id", ondelete="SET NULL"), index=True
    )

    small_group: Mapped["SmallGroup"] = relationship()
    no_meeting_week: Mapped["SmallGroupNoMeetingWeek | None"] = relationship()
    submitted_by: Mapped["Member | None"] = relationship(foreign_keys=[submitted_by_member_id])
    started_by: Mapped["Member"] = relationship(foreign_keys=[started_by_member_id])
    last_edited_by: Mapped["Member | None"] = relationship(foreign_keys=[last_edited_by_member_id])
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
