"""Generic in-app entries: a domain hands over `EntryRequest`s, this stores them as the recipients' list
(notifications spec, rule 1). Knows categories and templates, never conversations.

Unlike `create_deliveries` there is no preference filter (rule 2): everyone the domain decided on gets
the entry, before any channel's switch is applied.

`create_entries` also hands back each user's entry id and unread count, for the push channel (rule 5:
the push opens that entry, and its `badgeCount` is the unread count including it).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.notifications.models import UserNotification


@dataclass(frozen=True)
class EntryRequest:
    """One entry a domain wants in one person's list. `template`, `data` and `path` are exactly the
    email's. `small_group_ids` is for reminder entries only (rule 14)."""

    user_id: str
    category: str
    template: str
    data: Mapping[str, Any]
    path: str
    subject_key: str
    small_group_ids: Sequence[int] | None = None


@dataclass(frozen=True)
class EntryResult:
    """What a push needs about one stored entry: its id (`notificationId`) and the recipient's unread
    count after the insert, this entry included (`badgeCount`)."""

    notification_id: int
    unread: int


def create_entries(
    session: Session, source_event_id: int, requests: Sequence[EntryRequest]
) -> dict[str, EntryResult]:
    """Store the entries, inside the event's transaction. A retried event inserts nothing twice (unique
    per event and user). Returns, for every requested user, the entry's id and that user's unread count
    now, in this same transaction. On a retry the rows already exist (`on conflict do nothing` returns
    nothing for them), so their ids are read back by `(source_event_id, user_id)`."""
    if not requests:
        return {}
    rows = [
        {
            "user_id": r.user_id,
            "source_event_id": source_event_id,
            "category": r.category,
            "template": r.template,
            "data": dict(r.data),
            "path": r.path,
            "subject_key": r.subject_key,
            "small_group_ids": list(r.small_group_ids) if r.small_group_ids is not None else None,
        }
        for r in requests
    ]
    session.execute(
        insert(UserNotification)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["source_event_id", "user_id"])
    )
    # One read for new and already-stored rows alike (our own insert is visible in this transaction).
    n = UserNotification
    id_rows = session.execute(
        select(n.user_id, n.id).where(
            n.source_event_id == source_event_id, n.user_id.in_(list({r.user_id for r in requests}))
        )
    ).all()
    ids = {user_id: entry_id for user_id, entry_id in id_rows}
    unread_rows = session.execute(
        select(n.user_id, func.count())
        .where(n.user_id.in_(list(ids)), n.read_at.is_(None))
        .group_by(n.user_id)
    ).all()
    unread = {user_id: count for user_id, count in unread_rows}
    return {user_id: EntryResult(entry_id, unread.get(user_id, 0)) for user_id, entry_id in ids.items()}


@dataclass(frozen=True)
class EntryPage:
    """One page of a person's list: newest first. `next_before` is the id to pass as `before` for the
    next page, None on the last one."""

    items: Sequence[UserNotification]
    next_before: int | None


def list_entries(session: Session, user_id: str, *, limit: int, before: int | None) -> EntryPage:
    """The caller's entries, newest first, `limit` at a time, those with an id below `before`. Reads one
    row more than asked, to know whether there is another page without a count."""
    n = UserNotification
    query = select(n).where(n.user_id == user_id).order_by(n.id.desc()).limit(limit + 1)
    if before is not None:
        query = query.where(n.id < before)
    rows = list(session.scalars(query))
    page = rows[:limit]
    return EntryPage(items=page, next_before=page[-1].id if len(rows) > limit else None)


def unread_count(session: Session, user_id: str) -> int:
    """How many of the caller's kept entries are unread. Called on every page: it only touches the
    partial index on unread rows."""
    n = UserNotification
    return session.scalar(select(func.count()).where(n.user_id == user_id, n.read_at.is_(None))) or 0


def mark_entry_read(session: Session, user_id: str, entry_id: int) -> str | None:
    """Rule 13, opening an entry: read now (unchanged when it already was), and the entry's `path`.
    None when it isn't the caller's or is gone. One statement, so it is idempotent."""
    n = UserNotification
    path = session.scalar(
        update(n)
        .where(n.id == entry_id, n.user_id == user_id)
        .values(read_at=func.coalesce(n.read_at, func.now()))
        .returning(n.path)
    )
    session.commit()
    return path


def mark_all_entries_read(session: Session, user_id: str) -> int:
    """Rule 13, *Mark all read*: every unread entry of the caller. Returns how many were marked."""
    n = UserNotification
    result = session.execute(
        update(n).where(n.user_id == user_id, n.read_at.is_(None)).values(read_at=func.now()).returning(n.id)
    )
    marked = len(result.all())
    session.commit()
    return marked


def mark_subjects_read(session: Session, user_id: str, subject_keys: Sequence[str]) -> int:
    """Rules 13 and 14: set `read_at` on the user's unread entries about these subjects, in the caller's
    transaction (never commits). Returns how many were marked."""
    if not subject_keys:
        return 0
    n = UserNotification
    result = session.execute(
        update(n)
        .where(n.user_id == user_id, n.subject_key.in_(subject_keys), n.read_at.is_(None))
        .values(read_at=func.now())
        .returning(n.id)
    )
    return len(result.all())
