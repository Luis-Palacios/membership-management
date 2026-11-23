from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class NotificationPreference(MemberManagementBase):
    """A user's choice for one category on one channel. No row = enabled, so only people who change
    something get a row, and a new category starts on for everyone."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)  # auth-server user id, no FK
    category: Mapped[str] = mapped_column(String(32), primary_key=True)  # report_conversation
    channel: Mapped[str] = mapped_column(String(16), primary_key=True)  # email | push
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
