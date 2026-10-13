from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Identity, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.small_group_report import SmallGroupReport


class SmallGroupReportAttendance(MemberManagementBase):
    """One member's line in a small group report, entered by the report's submitter.

    Created for every member active in the group on the report's meeting_date, so "absent" is an
    explicit False rather than a missing row.
    """

    __tablename__ = "small_group_report_attendances"
    __table_args__ = (UniqueConstraint("report_id", "member_id"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("small_group_reports.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    attended_group: Mapped[bool]
    # Attended church the most recent Sunday on or before the report's meeting_date.
    attended_church: Mapped[bool]
    # Pastoral note about this person: expose to elders only, never with the general report.
    observation: Mapped[str | None] = mapped_column(Text)

    report: Mapped["SmallGroupReport"] = relationship(back_populates="attendances")
    member: Mapped["Member"] = relationship()
