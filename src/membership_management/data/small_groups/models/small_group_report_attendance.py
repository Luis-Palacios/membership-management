from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.guests.models import Guest
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.small_group_report import SmallGroupReport


class SmallGroupReportAttendance(MemberManagementBase):
    """One person's line (a member's or a guest's) in a small group report, entered by the report's submitter.

    Created for everyone active in the group on the report's meeting_date, so "absent" is an
    explicit False rather than a missing row. Exactly one of `member_id`, `guest_id`.
    """

    __tablename__ = "small_group_report_attendances"
    __table_args__ = (
        # NULLs are distinct in Postgres, so a guest's row never collides with a member's here.
        UniqueConstraint("report_id", "member_id"),
        # Named: the convention's `uq` name uses only the first column, which the one above already took.
        UniqueConstraint(
            "report_id", "guest_id", name="uq_small_group_report_attendances_report_id_guest_id"
        ),
        CheckConstraint("num_nonnulls(member_id, guest_id) = 1", name="one_person"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("small_group_reports.id"), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), index=True)
    attended_group: Mapped[bool]
    # Attended church the most recent Sunday on or before the report's meeting_date.
    attended_church: Mapped[bool]
    # Pastoral note about this person: expose to elders only, never with the general report.
    observation: Mapped[str | None] = mapped_column(Text)

    report: Mapped["SmallGroupReport"] = relationship(back_populates="attendances")
    member: Mapped["Member | None"] = relationship()
    guest: Mapped["Guest | None"] = relationship()
