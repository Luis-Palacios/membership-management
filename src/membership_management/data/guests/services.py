from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from membership_management.data.guests.models import (
    Guest,
    GuestInactiveReason,
    GuestStatus,
    GuestStatusChange,
)
from membership_management.data.members.models import Member, MemberSex
from membership_management.data.small_groups.models import LeftReason, SmallGroupMember


class InvitedByNotFoundError(Exception):
    """`invited_by_member_id` names no member."""


class GuestAlreadyInactiveError(Exception):
    """The guest is already inactive."""


class GuestAlreadyActiveError(Exception):
    """The guest is already active."""


class GuestEffectiveDateInFutureError(Exception):
    """The date the guest left is after today."""


@dataclass(frozen=True)
class NewGuest:
    """The fields a caller may set when creating a guest (already trimmed by the schema)."""

    name: str
    phone: str | None = None
    email: str | None = None
    sex: MemberSex | None = None
    address: str | None = None
    first_visit_date: date | None = None
    invited_by_member_id: int | None = None


def add_guest(
    session: Session, new: NewGuest, *, created_by_member_id: int | None, default_first_visit: date
) -> Guest:
    """Insert a guest and flush so it has an id; the caller commits (adding to a group is one transaction).

    No duplicate check, on purpose: families share phones and emails, and search is what catches likely
    duplicates before the form is submitted (rule 13).
    """
    if new.invited_by_member_id is not None and session.get(Member, new.invited_by_member_id) is None:
        raise InvitedByNotFoundError
    guest = Guest(
        name=new.name,
        phone=new.phone,
        email=new.email,
        sex=new.sex,
        address=new.address,
        first_visit_date=new.first_visit_date or default_first_visit,
        invited_by_member_id=new.invited_by_member_id,
        created_by_member_id=created_by_member_id,
    )
    session.add(guest)
    session.flush()
    return guest


def create_guest(session: Session, new: NewGuest, *, created_by_member_id: int | None, today: date) -> Guest:
    """Create a guest in no group and commit."""
    guest = add_guest(session, new, created_by_member_id=created_by_member_id, default_first_visit=today)
    session.commit()
    return guest


def update_guest(session: Session, guest: Guest, changes: dict[str, object]) -> Guest:
    """Apply only the given fields (the ones the client actually sent) and commit."""
    invited_by = changes.get("invited_by_member_id")
    if isinstance(invited_by, int) and session.get(Member, invited_by) is None:
        raise InvitedByNotFoundError
    for field, value in changes.items():
        setattr(guest, field, value)
    session.commit()
    return guest


def end_guest_period(period: SmallGroupMember, *, left_at: date, left_reason: LeftReason | None) -> None:
    """Close a guest's group period; the row stays as history. The caller commits."""
    period.left_at = left_at
    period.left_reason = left_reason


def deactivate_guest(
    session: Session,
    guest: Guest,
    *,
    reason: GuestInactiveReason,
    effective_date: date,
    note: str | None,
    changed_by_user_id: str,
    today: date,
) -> Guest:
    """Mark the guest inactive and end their open group period today (rule 5), in one transaction.

    `effective_date` (the date they left) is only recorded; it never moves the period's `left_at`.
    """
    # Lock the row, so two deactivations (or a deactivation and a reactivation) queue up.
    session.refresh(guest, with_for_update=True)
    if guest.status == GuestStatus.INACTIVE:
        session.rollback()
        raise GuestAlreadyInactiveError
    if effective_date > today:
        session.rollback()
        raise GuestEffectiveDateInFutureError
    # At most one: the partial unique index on active guest periods.
    period = session.scalar(
        select(SmallGroupMember).where(
            SmallGroupMember.guest_id == guest.id, SmallGroupMember.left_at.is_(None)
        )
    )
    if period is not None:
        end_guest_period(period, left_at=today, left_reason=LeftReason.GUEST_INACTIVE)
    _record_status_change(
        session,
        guest,
        GuestStatus.INACTIVE,
        reason=reason,
        effective_date=effective_date,
        note=note,
        changed_by_user_id=changed_by_user_id,
    )
    session.commit()
    return guest


def reactivate_guest(
    session: Session, guest: Guest, *, note: str | None, changed_by_user_id: str, today: date
) -> Guest:
    """Mark the guest active from today. Their group is not restored (rule 6)."""
    session.refresh(guest, with_for_update=True)
    if guest.status == GuestStatus.ACTIVE:
        session.rollback()
        raise GuestAlreadyActiveError
    _record_status_change(
        session,
        guest,
        GuestStatus.ACTIVE,
        reason=None,
        effective_date=today,
        note=note,
        changed_by_user_id=changed_by_user_id,
    )
    session.commit()
    return guest


def _record_status_change(
    session: Session,
    guest: Guest,
    status: GuestStatus,
    *,
    reason: GuestInactiveReason | None,
    effective_date: date,
    note: str | None,
    changed_by_user_id: str,
) -> None:
    """Append the history row and copy it onto the guest (rule 2); the caller commits."""
    now = datetime.now(UTC)
    session.add(
        GuestStatusChange(
            guest_id=guest.id,
            status=status,
            reason=reason,
            effective_date=effective_date,
            note=note,
            changed_by_user_id=changed_by_user_id,
            created_at=now,
        )
    )
    guest.status = status
    guest.status_changed_at = now
