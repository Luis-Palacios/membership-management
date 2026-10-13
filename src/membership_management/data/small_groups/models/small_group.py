from datetime import date

from sqlalchemy import Date, Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class SmallGroup(MemberManagementBase):
    __tablename__ = "small_groups"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    meeting_address: Mapped[str | None] = mapped_column(String(255))

    # Groups are closed, never deleted, so their membership and leadership history survives
    # (small_group_members' foreign key blocks deleting a group that has any history).
    # Leaders are small_group_members rows with role "leader"/"co_leader", not a column here.
    closed_at: Mapped[date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"<SmallGroup(id={self.id}, name={self.name})>"
