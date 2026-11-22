"""Sending due deliveries through a Sender (spec, *Sending a delivery*, *Failures and retries*).
Generic: categories and channels, never conversations. Never holds a DB transaction open across a
network call: read in one short session, send, record the outcome (fenced) in another."""

import logging
import threading
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session, sessionmaker

from membership_management.data.claiming import (
    claim,
    fenced_update,
    record_exception,
    record_transient,
    release,
)
from membership_management.data.notifications.models import NotificationDelivery
from membership_management.notifications.deliveries import is_enabled
from membership_management.notifications.sender import Sender

logger = logging.getLogger(__name__)

DELIVERIES = cast("Table", NotificationDelivery.__table__)


def idempotency_key(delivery_id: int) -> str:
    return f"mm:notification-delivery:{delivery_id}"


@dataclass
class SendStats:
    claimed: int = 0  # every row the claim returned (a full batch means more may be due)
    sent: int = 0
    dead: int = 0
    transient: int = 0
    failed: int = 0  # exceptions in our code
    suppressed: int = 0
    expired: int = 0
    released: int = 0
    lost: int = 0  # leases lost to another worker

    def did_something(self) -> bool:
        return any(vars(self).values())


def send_due_deliveries(
    sessions: sessionmaker[Session],
    sender: Sender,
    *,
    source_event_id: int | None = None,
    stop: threading.Event | None = None,
) -> SendStats:
    """One batch: claim, then per delivery re-check the deadline and the recipient's preference, send,
    record. A transient error stops the batch: the untried rows are released for the next run (the
    dependency is down; hammering it helps nobody). `source_event_id` is the fast path's filter;
    `stop` is checked between deliveries (shutdown: the rest is released)."""
    where = [DELIVERIES.c.source_event_id == source_event_id] if source_event_id is not None else []
    with sessions() as session:
        result = claim(session, DELIVERIES, "sending", where=where)
        session.commit()
    stats = SendStats(
        claimed=len(result.claimed) + result.expired + result.dead, expired=result.expired, dead=result.dead
    )
    rows = result.claimed
    for index, row in enumerate(rows):
        if stop is not None and stop.is_set():
            with sessions() as session:
                stats.released += sum(release(session, DELIVERIES, r) for r in rows[index:])
                session.commit()
            break
        with sessions() as session:
            delivery = session.get(NotificationDelivery, row.id)
            past_deadline = session.scalar(
                select(NotificationDelivery.expires_at <= func.now()).where(NotificationDelivery.id == row.id)
            )
            if delivery is None or past_deadline:
                # Checked again right before sending: no wave of old emails after an outage.
                _count(stats, "expired", fenced_update(session, DELIVERIES, row, status="expired"))
                session.commit()
                continue
            if not is_enabled(session, delivery.recipient_user_id, delivery.category, delivery.channel):
                # Turned off after it was queued: final, not a failure; the domain's throttle stays as is.
                _count(stats, "suppressed", fenced_update(session, DELIVERIES, row, status="suppressed"))
                session.commit()
                continue
            payload = dict(delivery.payload)
        try:
            outcome = sender.send(payload, idempotency_key(row.id))
        except Exception as exc:
            logger.exception("sending delivery %s raised", row.id)
            with sessions() as session:
                _count(stats, "failed", record_exception(session, DELIVERIES, row, type(exc).__name__))
                session.commit()
            continue
        with sessions() as session:
            if outcome.status == "sent":
                done = {"status": "sent", "sent_at": func.now(), "last_error": None}
                ok = fenced_update(session, DELIVERIES, row, **done)
            elif outcome.status == "dead":
                error = (outcome.error or "dead")[:200]
                ok = fenced_update(session, DELIVERIES, row, status="dead", last_error=error)
            else:
                ok = record_transient(session, DELIVERIES, row, outcome.error or "transient")
                untried = rows[index + 1 :]
                stats.released += sum(release(session, DELIVERIES, r) for r in untried)
            _count(stats, outcome.status, ok)
            session.commit()
        if outcome.status == "transient":
            break
    return stats


def _count(stats: SendStats, field: str, ok: bool) -> None:
    if ok:
        setattr(stats, field, getattr(stats, field) + 1)
    else:
        stats.lost += 1
        logger.warning("lost the lease on a delivery while recording '%s'", field)
