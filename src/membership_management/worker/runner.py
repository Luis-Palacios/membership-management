"""The worker's loop (spec, *The worker*): `run_once()` does one sweep, `run_forever()` repeats it.

Synchronous on purpose: the DB layer is sync. Embedded in the API, `run_forever` runs in one thread
through its own `CapacityLimiter(1)` (see `api/main.py`); standalone, `python -m
membership_management.worker` runs it in the main thread.
"""

import logging
import random
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from membership_management.data.claiming import BATCH_SIZE
from membership_management.data.database import MembershipSessionLocal
from membership_management.data.small_groups.conversation_notifications import WATCHER_PERMISSIONS
from membership_management.notifications.auth_server import (
    AuthServerSender,
    AuthServerUnavailable,
    users_with_permissions,
)
from membership_management.notifications.config import notification_settings
from membership_management.notifications.sender import Sender
from membership_management.notifications.sending import SendStats, send_due_deliveries
from membership_management.worker.events import EventStats, process_due_events
from membership_management.worker.maintenance import (
    ENTRIES_NAME,
    PURGE_BATCHES_PER_RUN,
    QUEUES,
    QueueHealth,
    expire_overdue,
    health,
    purge,
    purge_entries,
)
from membership_management.worker.reminder_trigger import trigger_report_reminder

logger = logging.getLogger(__name__)

INTERVAL = timedelta(minutes=2)
START_JITTER_SECONDS = 30
# Batches per table per run: drains a backlog without letting one run hold the thread for long.
MAX_BATCHES = 10


@dataclass
class RunReport:
    reachable: bool = True
    expired: dict[str, int] = field(default_factory=dict)
    reminder_triggered: bool = False  # this sweep wrote the week's report reminder event
    events: EventStats = field(default_factory=EventStats)
    deliveries: SendStats = field(default_factory=SendStats)
    purged: dict[str, int] = field(default_factory=dict)
    health: dict[str, QueueHealth] = field(default_factory=dict)

    def did_something(self) -> bool:
        return (
            not self.reachable
            or any(self.expired.values())
            or self.reminder_triggered
            or any(self.purged.values())
            or self.events.did_something()
            or self.deliveries.did_something()
        )


def _add(total: EventStats | SendStats, batch: EventStats | SendStats) -> None:
    for name, value in vars(batch).items():
        setattr(total, name, getattr(total, name) + value)


def run_once(
    stop: threading.Event | None = None,
    *,
    sessions: sessionmaker[Session] = MembershipSessionLocal,
    sender: Sender | None = None,
) -> RunReport:
    """One sweep: expire, then (only if auth-server answers) process due events and send due
    deliveries, then purge and measure. `stop` ends it early between items (shutdown)."""
    stop = stop or threading.Event()
    sender = sender or AuthServerSender()
    report = RunReport()

    with sessions() as session:
        report.expired = {q.name: expire_overdue(session, q) for q in QUEUES}
        session.commit()

    # The weekly report reminder (spec, rule 2): its event is written before the claim below, so a
    # sweep that triggers it can process it right away. A failure here never stops the rest of the sweep.
    try:
        with sessions() as session:
            report.reminder_triggered = trigger_report_reminder(session)
    except Exception:
        logger.exception("emails: the report reminder trigger failed")

    # Dependencies first, then claim: the possible watchers are needed to process anything, and if
    # auth-server can't be reached, nothing is claimed from either table this sweep. With every email
    # switch off (the worker runs only for the in-app purge), there is no token and nothing to send:
    # skip straight to maintenance, as before the in-app list existed.
    watchers = None
    if notification_settings.any_emails_enabled:
        try:
            watchers = users_with_permissions(WATCHER_PERMISSIONS)
        except AuthServerUnavailable:
            report.reachable = False

    if watchers is not None:
        for _ in range(MAX_BATCHES):
            if stop.is_set():
                break
            batch = process_due_events(sessions, watchers, stop=stop)
            _add(report.events, batch)
            if batch.claimed < BATCH_SIZE or batch.transient:
                break
        for _ in range(MAX_BATCHES):
            if stop.is_set():
                break
            sent = send_due_deliveries(sessions, sender, stop=stop)
            _add(report.deliveries, sent)
            if sent.claimed < BATCH_SIZE or sent.transient:
                break

    for queue in QUEUES:
        removed = 0
        for _ in range(PURGE_BATCHES_PER_RUN):
            with sessions() as session:
                n = purge(session, queue)
                session.commit()
            removed += n
            if n == 0 or stop.is_set():
                break
        report.purged[queue.name] = removed

    # The in-app list's 90-day retention (notifications spec, rule 16), batched the same way.
    removed = 0
    for _ in range(PURGE_BATCHES_PER_RUN):
        with sessions() as session:
            n = purge_entries(session)
            session.commit()
        removed += n
        if n == 0 or stop.is_set():
            break
    report.purged[ENTRIES_NAME] = removed

    with sessions() as session:
        report.health = {q.name: health(session, q) for q in QUEUES}
    _log(report)
    return report


def _log(report: RunReport) -> None:
    dead = sum(h.dead for h in report.health.values())
    level = logging.INFO if report.did_something() or dead else logging.DEBUG
    ages = {name: h.oldest_pending_seconds for name, h in report.health.items()}
    e, d = report.events, report.deliveries
    logger.log(
        level,
        "emails: reachable=%s reminder_triggered=%s | events processed=%d deliveries=%d failed=%d "
        "transient=%d dead=%d expired=%d | sends sent=%d dead=%d failed=%d transient=%d suppressed=%d "
        "expired=%d released=%d | "
        "expired overdue=%s purged=%s | oldest pending s=%s dead rows=%s",
        report.reachable,
        report.reminder_triggered,
        e.processed,
        e.deliveries,
        e.failed,
        e.transient,
        e.dead,
        e.expired,
        d.sent,
        d.dead,
        d.failed,
        d.transient,
        d.suppressed,
        d.expired,
        d.released,
        report.expired,
        report.purged,
        {k: round(v) if v is not None else None for k, v in ages.items()},
        {name: h.dead for name, h in report.health.items()},
    )
    if not report.reachable:
        logger.warning("emails: auth-server unreachable, nothing claimed this sweep")


def run_forever(stop: threading.Event) -> None:
    """Every 2 minutes after a random 0-30 s start (so several tasks don't sweep in step), until `stop`
    is set. Waits on `stop`, so shutdown never waits out the interval. One failed run never ends it."""
    if stop.wait(random.uniform(0, START_JITTER_SECONDS)):  # noqa: S311 (jitter, not security)
        return
    logger.info("email worker started")
    while not stop.is_set():
        try:
            run_once(stop)
        except Exception:
            logger.exception("email worker: run failed")
        stop.wait(INTERVAL.total_seconds())
    logger.info("email worker stopped")
