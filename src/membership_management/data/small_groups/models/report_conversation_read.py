from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class ReportConversationRead(MemberManagementBase):
    """When a user last opened a conversation. `user_id` is an auth-server user: no foreign key."""

    __tablename__ = "report_conversation_reads"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
