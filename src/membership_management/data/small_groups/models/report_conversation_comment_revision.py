from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Identity, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from membership_management.data.database import MemberManagementBase

if TYPE_CHECKING:
    from membership_management.data.small_groups.models.report_conversation_comment import (
        ReportConversationComment,
    )


class ReportConversationCommentRevision(MemberManagementBase):
    """The text a comment had before an edit. Kept for pastoral accountability, never returned by the API."""

    __tablename__ = "report_conversation_comment_revisions"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("report_conversation_comments.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    replaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    comment: Mapped["ReportConversationComment"] = relationship(back_populates="revisions")
