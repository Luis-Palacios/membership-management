from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from membership_management.data.guests.models import Guest
from membership_management.data.members.models import Member, MemberSex


class InvitedByNotFoundError(Exception):
    """`invited_by_member_id` names no member."""


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
