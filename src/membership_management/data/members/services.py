from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member
from membership_management.data.members.queries import list_members_query, member_active_small_groups_query
from membership_management.data.members.results import MemberSmallGroup, MemberSummary
from membership_management.data.query_helpers import all_as


class DuplicateMemberEmailError(Exception):
    """Another member already has this email."""


class MemberAlreadyLinkedError(Exception):
    """The member is already linked to a different user."""


class UserAlreadyLinkedError(Exception):
    """Another member is already linked to this user."""


def list_members(session: Session) -> Sequence[MemberSummary]:
    return all_as(session, list_members_query(), MemberSummary)


def get_member(session: Session, member_id: int) -> Member | None:
    return session.get(Member, member_id)


def get_member_small_groups(session: Session, member_id: int) -> Sequence[MemberSmallGroup]:
    return all_as(session, member_active_small_groups_query(member_id), MemberSmallGroup)


def create_member(
    session: Session,
    *,
    name: str,
    email: str | None,
    phone: str | None,
    address: str | None,
    birth_date: date | None,
) -> Member:
    member = Member(name=name, email=email, phone=phone, address=address, birth_date=birth_date)
    session.add(member)
    _flush_or_raise_duplicate(session)
    session.commit()
    return member


def update_member(session: Session, member: Member, changes: dict[str, object]) -> Member:
    """Apply only the given fields (the ones the client actually sent) and commit."""
    for field, value in changes.items():
        setattr(member, field, value)
    _flush_or_raise_duplicate(session)
    session.commit()
    return member


def link_member_user(session: Session, member: Member, user_id: str) -> Member:
    """Link the member to an auth-server user. Idempotent for the same user.

    The user id is not checked against auth-server (separate DB); callers only offer real users.
    """
    if member.user_id == user_id:
        return member
    if member.user_id is not None:
        raise MemberAlreadyLinkedError
    taken = session.scalar(select(Member.id).where(Member.user_id == user_id))
    if taken is not None:
        raise UserAlreadyLinkedError
    member.user_id = user_id
    try:
        session.flush()
    except IntegrityError as exc:
        # Lost a race with another link of the same user between the check and the flush.
        session.rollback()
        if "uq_members_user_id" in str(exc.orig):
            raise UserAlreadyLinkedError from exc
        raise
    session.commit()
    return member


def unlink_member_user(session: Session, member: Member) -> None:
    """Clear the member's user link. A no-op if it isn't linked."""
    if member.user_id is None:
        return
    member.user_id = None
    session.commit()


def _flush_or_raise_duplicate(session: Session) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_members_email" in str(exc.orig):
            raise DuplicateMemberEmailError from exc
        raise
