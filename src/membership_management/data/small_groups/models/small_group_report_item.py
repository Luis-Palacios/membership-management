from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Identity, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase
from membership_management.data.small_groups.models.report_conversation import ReportSection

if TYPE_CHECKING:
    from membership_management.data.small_groups.models.small_group_report import SmallGroupReport
    from membership_management.data.small_groups.models.small_group_report_item_person import (
        SmallGroupReportItemPerson,
    )


class SmallGroupReportItem(MemberManagementBase):
    """One prayer request, reason for praise or point for the elders in a held report (report tags rule 1).

    `text` holds tagged people as tokens (`report_items.py`); `people` indexes them and always matches.
    Writing a report replaces all its items, so `id` isn't stable across edits: don't anchor to it.
    """

    __tablename__ = "small_group_report_items"
    __table_args__ = (
        # Named: the convention's `uq` name uses only the first column, which would clash with a later one.
        UniqueConstraint(
            "report_id", "section", "position", name="uq_small_group_report_items_report_section_position"
        ),
        CheckConstraint("section IN ('prayer', 'praise', 'followUp')", name="section_valid"),
        CheckConstraint("position >= 0", name="position_not_negative"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    # The cascade is the database's: deleting a report deletes its items.
    report_id: Mapped[int] = mapped_column(
        ForeignKey("small_group_reports.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[ReportSection] = mapped_column(String(16))
    # Order inside the section, from 0.
    position: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(Text)

    report: Mapped["SmallGroupReport"] = relationship(back_populates="items")
    people: Mapped[list["SmallGroupReportItemPerson"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )
