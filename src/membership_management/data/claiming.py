"""The lease pattern shared by outbox_events and notification_deliveries (spec, *Processing and
sending*): claim a batch with SKIP LOCKED, then every later write is fenced on the claim token.

A claim is its own short transaction (commit right after `claim`), so the lease is visible to every
other worker before any work starts. Zero rows from a fenced write means the lease was lost (it ran
out and another worker took the row): log it and undo nothing else.

Functions take the `Table` (`OutboxEvent.__table__`, `NotificationDelivery.__table__`), so the same
code serves both tables.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Table, case, func, or_, select, update
from sqlalchemy.orm import Session

BATCH_SIZE = 10
# Lease rule: lease > batch x per-item timeout + margin (10 x 5 s + margin < 2 min).
LEASE = timedelta(minutes=2)
# Claims that ended in a crash, hang or exception before the row goes `dead` (the poison cap).
MAX_ATTEMPTS = 5
# Backoff by `failures`: 1, 5, 15, 60 minutes, then every 60 minutes until the expiry.
_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60))


def backoff(failures: int) -> timedelta:
    return _BACKOFF[min(max(failures, 1), len(_BACKOFF)) - 1]


class Claimed(NamedTuple):
    id: int
    claim_token: uuid.UUID
    failures: int


class ClaimResult(NamedTuple):
    claimed: list[Claimed]  # in progress, to work now
    expired: int  # past their deadline: `expired` instead of worked
    dead: int  # claimed with `attempts` already at the cap: `dead` instead of worked


def claim(
    session: Session,
    table: Table,
    in_progress: str,
    *,
    where: Sequence[ColumnElement[bool]] = (),
    due_only: bool = True,
    statuses: Sequence[str] = ("pending", "failed"),
    limit: int = BATCH_SIZE,
) -> ClaimResult:
    """One statement: pick up to `limit` due rows (`FOR UPDATE SKIP LOCKED`, so two workers never get
    the same row and never wait on each other) and lease them: in-progress status, a new claim token,
    `attempts + 1` (counted now, so a crash or hang still counts), `next_attempt_at = now() + lease`.
    A row past `expires_at` becomes `expired`, one already at `MAX_ATTEMPTS` becomes `dead`.

    An in-progress row is due again once its lease ran out (its worker died). `due_only=False` and
    `statuses=("pending",)` are the fast path's: its own fresh row, never one the sweep holds.
    """
    c = table.c
    conditions = [c.status.in_([*statuses, in_progress] if due_only else statuses), *where]
    if due_only:
        conditions.append(c.next_attempt_at <= func.now())
    due = (
        select(c.id)
        .where(*conditions)
        .order_by(c.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .cte("due")
    )
    expired = c.expires_at <= func.now()
    poisoned = c.attempts >= MAX_ATTEMPTS
    finished = or_(expired, poisoned)
    rows = session.execute(
        update(table)
        .where(c.id == due.c.id)
        .values(
            status=case((expired, "expired"), (poisoned, "dead"), else_=in_progress),
            claim_token=case((finished, None), else_=func.gen_random_uuid()),
            attempts=case((finished, c.attempts), else_=c.attempts + 1),
            next_attempt_at=func.now() + LEASE,
            last_error=case((expired, c.last_error), (poisoned, "poison cap"), else_=c.last_error),
        )
        .returning(c.id, c.status, c.claim_token, c.failures)
    ).all()
    return ClaimResult(
        claimed=[Claimed(r.id, r.claim_token, r.failures) for r in rows if r.status == in_progress],
        expired=sum(r.status == "expired" for r in rows),
        dead=sum(r.status == "dead" for r in rows),
    )


def fenced_update(session: Session, table: Table, row: Claimed, **values: Any) -> bool:  # noqa: ANN401
    """Update a claimed row only while we still hold its lease; clears the token (the lease ends).
    False = lost: someone else owns the row now."""
    result = session.execute(
        update(table)
        .where(table.c.id == row.id, table.c.claim_token == row.claim_token)
        .values(claim_token=None, **values)
        .returning(table.c.id)
    )
    return result.first() is not None


def record_transient(session: Session, table: Table, row: Claimed, error: str) -> bool:
    """Dependency trouble: the attempt is given back (transient failures never make a row `dead`; they
    retry until the expiry), `failures + 1` drives the backoff."""
    return fenced_update(
        session,
        table,
        row,
        status="failed",
        attempts=table.c.attempts - 1,
        failures=table.c.failures + 1,
        next_attempt_at=func.now() + backoff(row.failures + 1),
        last_error=error[:200],
    )


def record_exception(session: Session, table: Table, row: Claimed, error: str) -> bool:
    """A bug or a DB error in our code: the attempt stays counted (toward the poison cap)."""
    return fenced_update(
        session,
        table,
        row,
        status="failed",
        failures=table.c.failures + 1,
        next_attempt_at=func.now() + backoff(row.failures + 1),
        last_error=error[:200],
    )


def release(session: Session, table: Table, row: Claimed) -> bool:
    """An untried row handed back (a transient send error stopped the batch): `pending`, the attempt
    given back, `next_attempt_at` left as the claim set it, so it's due when the lease would have ended."""
    return fenced_update(session, table, row, status="pending", attempts=table.c.attempts - 1)
