"""Expiry, retention and monitoring for the two queues (spec, *Expiry*, *Monitoring*, *Retention*)."""

from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy import Table, delete, func, or_, select, update
from sqlalchemy.orm import Session

from membership_management.notifications.sending import DELIVERIES
from membership_management.worker.events import EVENTS

# Rows deleted per statement, and statements per run: a long-overdue purge spreads over a few runs
# instead of one big delete holding locks.
PURGE_BATCH = 1000
PURGE_BATCHES_PER_RUN = 10


@dataclass(frozen=True)
class Queue:
    name: str
    table: Table
    in_progress: str
    final: tuple[str, ...]
    retention: timedelta


EVENT_QUEUE = Queue("events", EVENTS, "processing", ("processed", "expired", "dead"), timedelta(days=30))
DELIVERY_QUEUE = Queue(
    "deliveries", DELIVERIES, "sending", ("sent", "dead", "expired", "suppressed"), timedelta(days=90)
)
QUEUES = (EVENT_QUEUE, DELIVERY_QUEUE)


def expire_overdue(session: Session, queue: Queue) -> int:
    """Rows past their deadline that nobody is working: waiting (`pending`, `failed`), or in progress with
    a lease that ran out. A row under a live lease is left to its worker, which checks the deadline
    itself. The claim expires rows too; this also catches rows that won't be due again before their
    deadline (a long backoff), so the monitoring numbers stay true."""
    c = queue.table.c
    rows = session.execute(
        update(queue.table)
        .where(
            # Exactly the due-index's predicate, so the planner uses it with one scan.
            c.status.in_(("pending", "failed", queue.in_progress)),
            c.expires_at <= func.now(),
            or_(c.status != queue.in_progress, c.next_attempt_at <= func.now()),
        )
        .values(status="expired", claim_token=None)
        .returning(c.id)
    ).all()
    return len(rows)


def purge(session: Session, queue: Queue) -> int:
    """Final rows older than the retention, in bounded batches (each committed by the caller)."""
    c = queue.table.c
    old = (
        select(c.id)
        .where(c.status.in_(queue.final), c.created_at < func.now() - queue.retention)
        .limit(PURGE_BATCH)
        .scalar_subquery()
    )
    return len(session.execute(delete(queue.table).where(c.id.in_(old)).returning(c.id)).all())


class QueueHealth(NamedTuple):
    oldest_pending_seconds: float | None  # age of the oldest row not yet final; None when there's none
    dead: int


def health(session: Session, queue: Queue) -> QueueHealth:
    """The two numbers the alarms watch (Phase 9): how far behind the queue is, and how many rows died.
    A full count is fine at this size (purged after 30/90 days); an index can come with the alarms."""
    c = queue.table.c
    oldest, dead = session.execute(
        select(
            func.extract("epoch", func.now() - func.min(c.created_at).filter(c.status.not_in(queue.final))),
            func.count().filter(c.status == "dead"),
        )
    ).one()
    return QueueHealth(float(oldest) if oldest is not None else None, dead)
