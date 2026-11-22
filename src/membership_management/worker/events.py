"""Processing due outbox events (spec, *Processing and sending*, *Candidate snapshot*).

Per batch: claim (own transaction) → read each event's candidates (read-only) → one permissions
lookup for all of them, no DB transaction open → each event in its own transaction, whose first
statement is the fence. A failed lookup is transient for every claimed event: nothing is processed on
partial data. An exception while processing rolls the event's transaction back (throttle rows and the
fence included) and is recorded in a second short, fenced transaction.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session, sessionmaker

from membership_management.data.claiming import (
    Claimed,
    claim,
    fenced_update,
    record_exception,
    record_transient,
)
from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.access_rules import Perms
from membership_management.data.small_groups.conversation_notifications import (
    COMMENT_ADDED,
    candidate_user_ids,
    process_comment_added,
)
from membership_management.notifications.auth_server import AuthServerUnavailable, permissions_for

logger = logging.getLogger(__name__)

EVENTS = cast("Table", OutboxEvent.__table__)
# The event types this worker understands, with the payload version each was written in.
_KNOWN = {COMMENT_ADDED: 1}


@dataclass
class EventStats:
    processed: int = 0
    deliveries: int = 0
    transient: int = 0
    failed: int = 0  # exceptions in our code
    dead: int = 0
    expired: int = 0
    lost: int = 0

    def did_something(self) -> bool:
        return any(vars(self).values())


def process_due_events(
    sessions: sessionmaker[Session], possible_watchers: Collection[str], *, event_id: int | None = None
) -> EventStats:
    """One batch of due events. `event_id` is the fast path: that one event, only while still
    `pending` and ignoring its head start, so it never takes a row the sweep holds."""
    with sessions() as session:
        if event_id is None:
            result = claim(session, EVENTS, "processing")
        else:
            result = claim(
                session,
                EVENTS,
                "processing",
                where=[EVENTS.c.id == event_id],
                due_only=False,
                statuses=("pending",),
            )
        session.commit()
    stats = EventStats(expired=result.expired, dead=result.dead)
    if not result.claimed:
        return stats

    # The candidate snapshot, read-only.
    candidates: dict[int, frozenset[str]] = {}
    unknown: list[Claimed] = []
    with sessions() as session:
        ids = [r.id for r in result.claimed]
        events = {e.id: e for e in session.scalars(select(OutboxEvent).where(EVENTS.c.id.in_(ids)))}
        for row in result.claimed:
            event = events[row.id]
            if _KNOWN.get(event.event_type) != event.schema_version:
                unknown.append(row)
                continue
            candidates[row.id] = candidate_user_ids(session, event.payload, possible_watchers)

    if unknown:
        with sessions() as session:
            for row in unknown:
                logger.error("outbox event %s: unknown type or schema version", row.id)
                ok = fenced_update(session, EVENTS, row, status="dead", last_error="unknown event type")
                stats.dead += ok
            session.commit()
    known = [row for row in result.claimed if row.id in candidates]

    # One lookup for the whole batch, outside any transaction.
    try:
        perms = permissions_for(set().union(*candidates.values()))
    except AuthServerUnavailable as exc:
        with sessions() as session:
            for row in known:
                stats.transient += record_transient(session, EVENTS, row, f"permissions: {exc.args[0]}")
            session.commit()
        return stats

    for row in known:
        # Exactly this event's candidates: nobody else's permissions can reach its rules.
        event_perms = {u: perms[u] for u in candidates[row.id] if u in perms}
        _process_one(sessions, row, event_perms, possible_watchers, stats)
    return stats


def _process_one(
    sessions: sessionmaker[Session],
    row: Claimed,
    perms: dict[str, Perms],
    possible_watchers: Collection[str],
    stats: EventStats,
) -> None:
    with sessions() as session:
        try:
            # The fence, first: marks it processed if we still hold the lease, and locks the row so no
            # other task can work it while this transaction runs. Rolled back with everything else.
            done = {"status": "processed", "processed_at": func.now(), "last_error": None}
            if not fenced_update(session, EVENTS, row, **done):
                session.rollback()
                stats.lost += 1
                logger.warning("outbox event %s: lease lost before processing", row.id)
                return
            event = session.get_one(OutboxEvent, row.id)
            stats.deliveries += process_comment_added(session, event, perms, possible_watchers)
            session.commit()
            stats.processed += 1
        except Exception as exc:
            session.rollback()
            logger.exception("outbox event %s: processing raised", row.id)
            error = type(exc).__name__
        else:
            return
    with sessions() as session:
        if record_exception(session, EVENTS, row, error):
            stats.failed += 1
        else:
            stats.lost += 1
        session.commit()
