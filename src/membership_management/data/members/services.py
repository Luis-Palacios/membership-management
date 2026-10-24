from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.members.models import (
    Member,
    MemberInactiveReason,
    MemberSex,
    MemberStatus,
    MemberStatusChange,
)
from membership_management.data.members.queries import (
    list_members_query,
    member_active_in_open_groups_query,
    member_active_leads_query,
    member_active_small_groups_query,
    member_by_user_id_query,
    member_latest_status_change_query,
    member_open_leader_groups_query,
    member_options_query,
    member_past_small_groups_query,
    member_search_query,
    member_status_history_query,
)
from membership_management.data.members.results import (
    MemberLead,
    MemberLeadGroup,
    MemberOption,
    MemberPastSmallGroup,
    MemberSmallGroup,
    MemberStatusChangeRow,
    MemberSummary,
)
from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.models import LeftReason, SmallGroupMember


class DuplicateMemberEmailError(Exception):
    """Another member already has this email."""


class MemberAlreadyLinkedError(Exception):
    """The member is already linked to a different user."""


class UserAlreadyLinkedError(Exception):
    """Another member is already linked to this user."""


class MemberAlreadyInactiveError(Exception):
    """The member is already inactive."""


class MemberAlreadyActiveError(Exception):
    """The member is already active."""


class MemberLeadsGroupError(Exception):
    """The member is the leader of open groups, so they can't be deactivated (rule 7)."""

    def __init__(self, groups: Sequence[MemberLeadGroup]) -> None:
        super().__init__("The member leads open groups.")
        self.groups = groups


class EffectiveDateInFutureError(Exception):
    """The date the member left is after today."""


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


def get_member_latest_status_change(session: Session, member_id: int) -> MemberStatusChange | None:
    return session.scalar(member_latest_status_change_query(member_id))


def get_member_past_small_groups(session: Session, member_id: int) -> Sequence[MemberPastSmallGroup]:
    """The periods the member's latest deactivation ended (empty if they were never deactivated)."""
    return all_as(session, member_past_small_groups_query(member_id), MemberPastSmallGroup)


def get_member_status_history(session: Session, member_id: int) -> Sequence[MemberStatusChangeRow]:
    return all_as(session, member_status_history_query(member_id), MemberStatusChangeRow)


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


def deactivate_member(
    session: Session,
    member: Member,
    *,
    reason: MemberInactiveReason,
    effective_date: date,
    note: str | None,
    changed_by_user_id: str,
    today: date,
) -> Member:
    """Mark the member inactive and end every open group period today (rule 6), in one transaction.

    `effective_date` (the date they left) is only recorded; it never moves a period's `left_at`.
    """
    # Lock the row, so two deactivations (or a deactivation and a reactivation) queue up.
    session.refresh(member, with_for_update=True)
    if member.status == MemberStatus.INACTIVE:
        session.rollback()
        raise MemberAlreadyInactiveError
    leads = all_as(session, member_open_leader_groups_query(member.id), MemberLeadGroup)
    if leads:
        session.rollback()
        raise MemberLeadsGroupError(leads)
    if effective_date > today:
        session.rollback()
        raise EffectiveDateInFutureError
    session.execute(
        update(SmallGroupMember)
        .where(SmallGroupMember.member_id == member.id, SmallGroupMember.left_at.is_(None))
        # greatest() keeps the left_after_joined check satisfied for a not-yet-started membership.
        .values(
            left_at=func.greatest(SmallGroupMember.joined_at, today), left_reason=LeftReason.MEMBER_INACTIVE
        )
        # The ORM rows aren't touched afterwards, so don't spend a SELECT syncing them.
        .execution_options(synchronize_session=False)
    )
    _record_status_change(
        session,
        member,
        MemberStatus.INACTIVE,
        reason=reason,
        effective_date=effective_date,
        note=note,
        changed_by_user_id=changed_by_user_id,
    )
    session.commit()
    return member


def reactivate_member(
    session: Session, member: Member, *, note: str | None, changed_by_user_id: str, today: date
) -> Member:
    """Mark the member active from today. Their groups are not restored (rule 10)."""
    session.refresh(member, with_for_update=True)
    if member.status == MemberStatus.ACTIVE:
        session.rollback()
        raise MemberAlreadyActiveError
    _record_status_change(
        session,
        member,
        MemberStatus.ACTIVE,
        reason=None,
        effective_date=today,
        note=note,
        changed_by_user_id=changed_by_user_id,
    )
    session.commit()
    return member


def _record_status_change(
    session: Session,
    member: Member,
    status: MemberStatus,
    *,
    reason: MemberInactiveReason | None,
    effective_date: date,
    note: str | None,
    changed_by_user_id: str,
) -> None:
    """Append the history row and copy it onto the member (rule 2); the caller commits."""
    now = datetime.now(UTC)
    session.add(
        MemberStatusChange(
            member_id=member.id,
            status=status,
            reason=reason,
            effective_date=effective_date,
            note=note,
            changed_by_user_id=changed_by_user_id,
            created_at=now,
        )
    )
    member.status = status
    member.status_changed_at = now


def _flush_or_raise_duplicate(session: Session) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if "uq_members_email_lower" in str(exc.orig):
            raise DuplicateMemberEmailError from exc
        raise
