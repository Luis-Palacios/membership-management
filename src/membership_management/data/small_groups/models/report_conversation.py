from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.report_conversation_comment import (
        ReportConversationComment,
    )
    from membership_management.data.small_groups.models.small_group_report import SmallGroupReport

ConversationStatus = Literal["open", "resolved"]
# Which side of the conversation a comment is on: "elders" when the author had `smallGroups: all` when
# writing, otherwise "leaders". Stored on each comment so later role changes don't rewrite history.
ConversationSide = Literal["elders", "leaders"]


class ReportConversation(MemberManagementBase):
    """A thread about one person's attendance row in a small group report (one per report and member).

    The user ids are JWT `sub`s of auth-server users: string references with no foreign key. The
    `last_comment_*` columns are denormalised on every write so the inbox query stays simple.
    """

    __tablename__ = "report_conversations"
    __table_args__ = (
        UniqueConstraint("report_id", "member_id"),
        CheckConstraint("status IN ('open', 'resolved')", name="status_valid"),
        CheckConstraint("last_comment_side IN ('elders', 'leaders')", name="last_comment_side_valid"),
        CheckConstraint(
            "(status = 'open' AND resolved_by_user_id IS NULL AND resolved_by_member_id IS NULL"
            " AND resolved_at IS NULL)"
            " OR (status = 'resolved' AND resolved_by_user_id IS NOT NULL"
            " AND resolved_by_member_id IS NOT NULL AND resolved_at IS NOT NULL)",
            name="resolved_columns_match_status",
        ),
        Index("ix_report_conversations_last_comment_at_desc", desc("last_comment_at")),
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    # The cascade is the database's: deleting a report deletes its conversations.
    report_id: Mapped[int] = mapped_column(
        ForeignKey("small_group_reports.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(String(16), default="open")
    created_by_user_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[str | None] = mapped_column(String)
    resolved_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_comment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_comment_side: Mapped[ConversationSide] = mapped_column(String(8))
    last_comment_user_id: Mapped[str] = mapped_column(String)

    report: Mapped["SmallGroupReport"] = relationship(back_populates="conversations")
    member: Mapped["Member"] = relationship(foreign_keys=[member_id])
    resolved_by: Mapped["Member | None"] = relationship(foreign_keys=[resolved_by_member_id])
    comments: Mapped[list["ReportConversationComment"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )
