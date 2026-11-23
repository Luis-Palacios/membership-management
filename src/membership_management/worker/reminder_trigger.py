"""The weekly report reminder's trigger (report-reminder-emails spec, rules 1-4, *Scheduler step*).

Not an outbox event's consumer: this is what writes the event. `run_once` calls it every sweep; it
does nothing until the church's wall clock reaches this week's `scheduled_at`, and nothing again once
the 6 hour catch-up window has passed, so an outage never causes a late reminder.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.models import ReportReminderRun
from membership_management.data.small_groups.report_reminder_notifications import REMINDER_DUE
from membership_management.data.small_groups.services import church_sunday
from membership_management.notifications.config import notification_settings

# Rules 3-4: the trigger window, and the outbox event's and every delivery's lifetime, from scheduled_at.
WINDOW = timedelta(hours=6)


def scheduled_at_for(now_church: datetime, day: int, at: time) -> tuple[date, datetime]:
    """This church week's `week_start` (its Sunday) and the moment the reminder is due. Day 7 (Sunday)
    is offset 0, the start of the same week, not the Sunday after it."""
    week_start = church_sunday(now_church.date())
    offset = 0 if day == 7 else day
    target = week_start + timedelta(days=offset)
    return week_start, datetime.combine(target, at, tzinfo=now_church.tzinfo)


def trigger_report_reminder(session: Session, now: datetime | None = None) -> bool:
    """Write this week's `small_group_report.reminder_due` event if the reminder is due and no other
    sweep (or replica) has already. The `report_reminder_runs` insert and the event share one
    transaction, committed here. Returns whether an event was written. Does nothing with the switch off."""
    settings = notification_settings
    if not settings.report_reminder_emails_enabled:
        return False
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    now_church = now_utc.astimezone(ZoneInfo(settings.church_timezone))
    week_start, scheduled_at = scheduled_at_for(
        now_church, settings.report_reminder_day, settings.report_reminder_time
    )
    if not scheduled_at <= now_church < scheduled_at + WINDOW:
        return False
    claimed = session.scalar(
        insert(ReportReminderRun)
        .values(week_start=week_start)
        .on_conflict_do_nothing(index_elements=["week_start"])
        .returning(ReportReminderRun.week_start)
    )
    if claimed is None:  # another sweep already triggered this week
        session.rollback()
        return False
    session.add(
        OutboxEvent(
            event_type=REMINDER_DUE,
            schema_version=1,
            aggregate_type="small_group_report_reminder",
            aggregate_id=int(week_start.strftime("%Y%m%d")),
            payload={"weekStart": week_start.isoformat(), "scheduledAt": scheduled_at.isoformat()},
            created_at=now_utc,
            next_attempt_at=now_utc,
            expires_at=(scheduled_at + WINDOW).astimezone(UTC),
        )
    )
    session.commit()
    return True
