"""Watching groups (report conversations rules 18-22): who watches comes from permissions, so only the
opt-outs are stored. Channel-neutral: "watch this group", not "email me about this group"."""

from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.small_groups.models import SmallGroup, SmallGroupWatchOptOut


class WatchedGroup(NamedTuple):
    small_group_id: int
    name: str
    closed: bool
    watching: bool


def watched_groups(session: Session, user_id: str) -> list[WatchedGroup]:
    """Every group (the caller is full-scope: they watch all of them by default, closed ones too, rule 18),
    open first, then by name, with whether this user still watches it."""
    opt_out = SmallGroupWatchOptOut
    opted_out = set(session.scalars(select(opt_out.small_group_id).where(opt_out.user_id == user_id)))
    groups = session.execute(
        select(SmallGroup.id, SmallGroup.name, SmallGroup.closed_at.is_not(None).label("closed")).order_by(
            SmallGroup.closed_at.is_not(None), SmallGroup.name, SmallGroup.id
        )
    )
    return [WatchedGroup(g.id, g.name, g.closed, g.id not in opted_out) for g in groups]


def set_watching(session: Session, user_id: str, small_group_id: int, *, watching: bool) -> None:
    """Rule 21: unwatching inserts the opt-out, watching deletes it; both idempotent. Applies to emails
    planned after the change; one already queued still goes out. Committed here."""
    opt_out = SmallGroupWatchOptOut
    if watching:
        session.execute(
            delete(opt_out).where(opt_out.user_id == user_id, opt_out.small_group_id == small_group_id)
        )
    else:
        session.execute(
            insert(opt_out)
            .values(user_id=user_id, small_group_id=small_group_id)
            .on_conflict_do_nothing(index_elements=["user_id", "small_group_id"])
        )
    session.commit()
