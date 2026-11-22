from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class SmallGroupWatchOptOut(MemberManagementBase):
    """A full-scope user who stopped watching one group (rule 21). No row = watching: who watches
    comes from permissions (rule 18), so only the exceptions are stored, and a group created later,
    or a user who just gained access, is watched with no row written. Unwatching drops watcher emails
    only, never participant ones, and changes nothing in the app."""

    __tablename__ = "small_group_watch_opt_outs"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)  # auth-server user id, no FK
    small_group_id: Mapped[int] = mapped_column(
        ForeignKey("small_groups.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
