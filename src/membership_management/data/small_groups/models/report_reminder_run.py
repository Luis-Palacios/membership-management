from datetime import date, datetime

from sqlalchemy import Date, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from membership_management.data.database import MemberManagementBase


class ReportReminderRun(MemberManagementBase):
    """One row per church week whose report reminder batch was triggered (report-reminder-emails spec,
    rule 3). The worker inserts `week_start` with ON CONFLICT DO NOTHING in the same transaction as
    the outbox event, so at most one batch exists per week across sweeps and replicas."""

    __tablename__ = "report_reminder_runs"

    # The church Sunday (church_sunday()).
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
