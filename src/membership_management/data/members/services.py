from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member, MemberSex
from membership_management.data.members.queries import (
    list_members_query,
    member_active_in_open_groups_query,
    member_active_leads_query,
    member_active_small_groups_query,
    member_by_user_id_query,
    member_options_query,
    member_search_query,
)
from membership_management.data.members.results import (
    MemberLead,
    MemberOption,
    MemberSmallGroup,
    MemberSummary,
)
from membership_management.data.query_helpers import all_as


class DuplicateMemberEmailError(Exception):
    """Another member already has this email."""


class MemberAlreadyLinkedError(Exception):
    """The member is already linked to a different user."""


class UserAlreadyLinkedError(Exception):
    """Another member is already linked to this user."""


def list_members(session: Session) -> Sequence[MemberSummary]:
    return all_as(session, list_members_query(), MemberSummary)


def list_member_options(session: Session) -> Sequence[MemberOption]:
    return all_as(session, member_options_query(), MemberOption)


def search_members(
    session: Session, text: str, only_group_ids: frozenset[int] | None, *, everyone: bool, limit: int
) -> Sequence[MemberOption]:
    """Members matching `text` by name within the caller's scope (`everyone`, or `only_group_ids`)."""
    if not everyone and only_group_ids is not None and not only_group_ids:
        return []
    return all_as(
        session, member_search_query(text, only_group_ids, everyone=everyone, limit=limit), MemberOption
    )


def is_member_active_in_open_groups(
    session: Session, member_id: int, only_group_ids: frozenset[int] | None
) -> bool:
    """Whether the member is active in an open group among `only_group_ids` (`None`: any open group)."""
    if only_group_ids is not None and not only_group_ids:
        return False
    return session.scalar(member_active_in_open_groups_query(member_id, only_group_ids)) is not None


def get_member(session: Session, member_id: int) -> Member | None:
    return session.get(Member, member_id)


def get_member_by_user_id(session: Session, user_id: str) -> Member | None:
    """The member linked to this auth-server user, or None (a user needn't be a member)."""
    return session.scalar(member_by_user_id_query(user_id))


def get_member_leads(session: Session, member_id: int) -> Sequence[MemberLead]:
    return all_as(session, member_active_leads_query(member_id), MemberLead)


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
    sex: MemberSex | None,
) -> Member:
    member = Member(name=name, email=email, phone=phone, address=address, birth_date=birth_date, sex=sex)
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


def link_member_by_accepted_invite(session: Session, user_id: str, email: str) -> int | None:
    """Link the one unlinked member whose email matches (case-insensitive); return their id.

    Changes nothing and returns None when the user is already linked or no unlinked member has
    that email. Never raises for those cases: the caller is an invite acceptance that must not fail.
    """
    if session.scalar(select(Member.id).where(Member.user_id == user_id)) is not None:
        return None
    # lower(email) is unique, so at most one member can match.
    member = session.scalar(
        select(Member).where(func.lower(Member.email) == email.lower(), Member.user_id.is_(None))
    )
    if member is None:
        return None
    member.user_id = user_id
    try:
        session.commit()
    except IntegrityError:
        # Lost a race with another link of the same user; leave things as the winner set them.
        session.rollback()
        return None
    return member.id


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
        if "uq_members_email_lower" in str(exc.orig):
            raise DuplicateMemberEmailError from exc
        raise
