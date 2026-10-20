from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase
from membership_management.data.small_groups.models.report_conversation import ConversationSide

if TYPE_CHECKING:
    from membership_management.data.members.models import Member
    from membership_management.data.small_groups.models.report_conversation import ReportConversation
    from membership_management.data.small_groups.models.report_conversation_comment_revision import (
        ReportConversationCommentRevision,
    )


class ReportConversationComment(MemberManagementBase):
    __tablename__ = "report_conversation_comments"
    __table_args__ = (CheckConstraint("side IN ('elders', 'leaders')", name="side_valid"),)

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[str] = mapped_column(String)
    # Always set: commenting needs a linked member, and the member's name is what's shown.
    author_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    side: Mapped[ConversationSide] = mapped_column(String(8))
    # Kept after a soft delete but never returned by the API again.
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped["ReportConversation"] = relationship(back_populates="comments")
    author: Mapped["Member"] = relationship()
    revisions: Mapped[list["ReportConversationCommentRevision"]] = relationship(
        back_populates="comment", cascade="all, delete-orphan", passive_deletes=True
    )
