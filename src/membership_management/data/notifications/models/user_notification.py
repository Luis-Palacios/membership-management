from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class UserNotification(MemberManagementBase):
    """One entry in a user's in-app list (notifications spec, rule 1): what happened, whatever channel
    also told them. Written next to the deliveries from one event, with the email's own `template`,
    `data` and `path`, and never changed afterwards except `read_at`. Generic: knows categories and
    templates, not conversations."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        # A retried event can't write a second entry for the same person.
        UniqueConstraint("source_event_id", "user_id"),
        # The list: a person's entries, newest first, paged by id.
        Index("ix_user_notifications_user_id_id_desc", "user_id", text("id DESC")),
        # The bell's count, called on every page: only unread rows are in it.
        Index("ix_user_notifications_unread", "user_id", postgresql_where=text("read_at IS NULL")),
        # Rules 13 and 14: the entries about one thread, report or church week.
        Index("ix_user_notifications_subject_key", "subject_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String)  # auth-server user id, no FK
    # No FK: events are purged after 30 days, entries kept 90.
    source_event_id: Mapped[int] = mapped_column(BigInteger)
    # report_conversation | report_submitted | report_reminder
    category: Mapped[str] = mapped_column(String(32))
    # The email template name: report-conversation.new, report-conversation.reply, report.submitted,
    # report.reminder.
    template: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)  # exactly the email delivery's data
    path: Mapped[str] = mapped_column(Text)  # exactly the email delivery's path
    # report_conversation:{id} | small_group_report:{id} | report_reminder:{YYYY-MM-DD}
    subject_key: Mapped[str] = mapped_column(String(64))
    # Reminder entries only: the groups the person was reminded about (rule 14). Never returned.
    small_group_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
