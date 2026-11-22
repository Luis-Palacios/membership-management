from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class ReportConversationNotifyState(MemberManagementBase):
    """When a user was last notified about a conversation (rule 20: one email per conversation until
    they open it). Compared with their `report_conversation_reads.last_read_at`: notified after the
    last read = held. Stamped with the comment's time, not the worker's clock, so a read or Mark all
    read always lifts it. Per conversation, not per channel."""

    __tablename__ = "report_conversation_notify_state"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)  # auth-server user id, no FK
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="CASCADE"), primary_key=True
    )
    last_notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
