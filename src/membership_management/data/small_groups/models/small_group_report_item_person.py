from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Identity, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.small_groups.models.small_group_report_item import SmallGroupReportItem


class SmallGroupReportItemPerson(MemberManagementBase):
    """A person (member or guest) tagged in a report item: one row per token in the item's text."""

    __tablename__ = "small_group_report_item_people"
    __table_args__ = (
        # NULLs are distinct in Postgres, so a guest's row never collides with a member's here.
        UniqueConstraint("item_id", "member_id"),
        # Named: the convention's `uq` name uses only the first column, which the one above already took.
        UniqueConstraint("item_id", "guest_id", name="uq_small_group_report_item_people_item_id_guest_id"),
        CheckConstraint("num_nonnulls(member_id, guest_id) = 1", name="one_person"),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    # The cascade is the database's: deleting an item (or its report) deletes these rows.
    item_id: Mapped[int] = mapped_column(
        ForeignKey("small_group_report_items.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    guest_id: Mapped[int | None] = mapped_column(ForeignKey("guests.id"), index=True)

    item: Mapped["SmallGroupReportItem"] = relationship(back_populates="people")
