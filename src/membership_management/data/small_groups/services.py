from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member
from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.models import SmallGroup, SmallGroupMember, SmallGroupRole
from membership_management.data.small_groups.queries import (
    led_small_group_ids_query,
    list_small_groups_query,
    recent_attendance_marks_query,
    report_id_on_date_query,
    roster_periods_on_date_query,
    small_group_active_members_query,
)
from membership_management.data.small_groups.results import (
    AttendanceMark,
    ReportRoster,
    RosterPeriod,
    RosterPerson,
    SmallGroupActiveMember,
    SmallGroupSummary,
)

# Reports looked at for a "missed the last N meetings" hint (rule 11); plenty for a hint.
MISSED_STREAK_REPORT_WINDOW = 12


class SmallGroupAlreadyClosedError(Exception):
    """The group already has a closed_at date."""


class SmallGroupClosedError(Exception):
    """The group is closed, so its memberships can't change."""


class MemberNotFoundError(Exception):
    """No member with the given ID exists."""


class MemberAlreadyInGroupError(Exception):
    """The member already has an active membership in the group."""


class ActiveMembershipNotFoundError(Exception):
    """The member has no active membership in the group."""


class LeaderAlreadyExistsError(Exception):
    """The group already has an active leader."""


class ReportAlreadyExistsError(Exception):
    """The group already has a report for that meeting date (rule 1)."""

    def __init__(self, existing_id: int) -> None:
        super().__init__(existing_id)
        self.existing_id = existing_id


class MemberRequiredToSubmitError(Exception):
    """The caller has no linked member, and submitting a report needs one (rule 5)."""


class FutureMeetingDateError(Exception):
    """The meeting date is after today in the church's time zone (rule 2)."""


class AttendanceMismatchError(Exception):
    """The attendance rows don't match the group's members on the meeting date (rule 3)."""


class NotGroupLeaderOnDateError(Exception):
    """A scoped caller didn't hold leader or co-leader in the group on the meeting date (rule 5)."""


def church_sunday(d: date) -> date:
    """The most recent Sunday on or before `d` (rule 12); `d` itself when it is a Sunday."""
    return d - timedelta(days=d.isoweekday() % 7)


def list_small_groups(
    session: Session, only_ids: frozenset[int] | None = None
) -> Sequence[SmallGroupSummary]:
    """All groups, or just `only_ids` (a scoped caller's groups; empty means none, without a query)."""
    if only_ids is not None and not only_ids:
        return []
    return all_as(session, list_small_groups_query(only_ids), SmallGroupSummary)


def get_led_small_group_ids(session: Session, member_id: int) -> frozenset[int]:
    """The group ids a member may work on as a scoped role: led now, or led when the group closed."""
    return frozenset(session.scalars(led_small_group_ids_query(member_id)))


def get_small_group(session: Session, small_group_id: int) -> SmallGroup | None:
    return session.get(SmallGroup, small_group_id)


def get_small_group_active_members(session: Session, small_group_id: int) -> Sequence[SmallGroupActiveMember]:
    return all_as(session, small_group_active_members_query(small_group_id), SmallGroupActiveMember)


_ROLE_ORDER = {SmallGroupRole.LEADER: 0, SmallGroupRole.CO_LEADER: 1, SmallGroupRole.MEMBER: 2}


def roster_on_date(session: Session, small_group_id: int, d: date) -> list[RosterPerson]:
    """Everyone whose membership covers `d` (rule 3): leader, then co-leaders, then members, by name.

    `missed_streak` is filled in by `get_report_roster`; here it is 0.
    """
    best: dict[int, RosterPeriod] = {}
    for period in all_as(session, roster_periods_on_date_query(small_group_id, d), RosterPeriod):
        current = best.get(period.member_id)
        if current is None or _period_rank(period, d) > _period_rank(current, d):
            best[period.member_id] = period
    people = [
        RosterPerson(p.member_id, p.member_name, p.role, p.joined_at, missed_streak=0) for p in best.values()
    ]
    return sorted(people, key=lambda p: (_ROLE_ORDER[p.role], p.member_name, p.member_id))


def _period_rank(period: RosterPeriod, d: date) -> tuple[bool, date, int]:
    """Prefer the period still running at the end of `d` (a role change on `d`), else the latest."""
    return (period.left_at is None or period.left_at > d, period.joined_at, period.period_id)


def missed_streaks(
    session: Session, small_group_id: int, member_ids: Sequence[int], before: date
) -> dict[int, int]:
    """Per member, how many of the group's latest reports before `before` they missed in a row (rule 11).

    Counts the leading run of `attended_group = false`, newest report first; reports where the member
    has no row neither break nor extend it.
    """
    marks = all_as(
        session,
        recent_attendance_marks_query(small_group_id, before, MISSED_STREAK_REPORT_WINDOW),
        AttendanceMark,
    )
    streaks = dict.fromkeys(member_ids, 0)
    attended_since: set[int] = set()
    for mark in marks:
        if mark.member_id not in streaks or mark.member_id in attended_since:
            continue
        if mark.attended_group:
            attended_since.add(mark.member_id)
        else:
            streaks[mark.member_id] += 1
    return streaks


def get_report_roster(session: Session, small_group: SmallGroup, d: date, *, today: date) -> ReportRoster:
    """Who goes in a report for `d`, their missed streaks, and the report already filed for `d`, if any."""
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    if d > today:
        raise FutureMeetingDateError
    people = roster_on_date(session, small_group.id, d)
    streaks = missed_streaks(session, small_group.id, [p.member_id for p in people], d)
    return ReportRoster(
        people=[p._replace(missed_streak=streaks[p.member_id]) for p in people],
        existing_report_id=session.scalars(report_id_on_date_query(small_group.id, d)).one_or_none(),
    )


def create_small_group(
    session: Session, *, name: str, meeting_address: str | None, meeting_day: int | None
) -> SmallGroup:
    small_group = SmallGroup(name=name, meeting_address=meeting_address, meeting_day=meeting_day)
    session.add(small_group)
    session.commit()
    return small_group


def update_small_group(session: Session, small_group: SmallGroup, changes: dict[str, object]) -> SmallGroup:
    """Apply only the given fields (the ones the client actually sent) and commit."""
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    for field, value in changes.items():
        setattr(small_group, field, value)
    session.commit()
    return small_group


def close_small_group(session: Session, small_group: SmallGroup, closed_at: date) -> SmallGroup:
    """Close the group and end every active membership on the same date, keeping the history."""
    if small_group.closed_at is not None:
        raise SmallGroupAlreadyClosedError
    small_group.closed_at = closed_at
    session.execute(
        update(SmallGroupMember)
        .where(SmallGroupMember.small_group_id == small_group.id, SmallGroupMember.left_at.is_(None))
        # greatest() keeps the left_after_joined check satisfied for a not-yet-started membership.
        .values(left_at=func.greatest(SmallGroupMember.joined_at, closed_at))
    )
    session.commit()
    return small_group


def add_small_group_member(
    session: Session, small_group: SmallGroup, *, member_id: int, role: SmallGroupRole, today: date
) -> None:
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    if session.get(Member, member_id) is None:
        raise MemberNotFoundError
    if get_active_membership(session, small_group.id, member_id) is not None:
        raise MemberAlreadyInGroupError
    _ensure_leader_slot_free(session, small_group.id, role)
    _add_membership(session, small_group.id, member_id, role, today)
    _commit_or_raise_conflict(session)


def change_small_group_member_role(
    session: Session, small_group: SmallGroup, *, member_id: int, role: SmallGroupRole, today: date
) -> None:
    """Change the role by closing the current period and opening a new one (kept as history)."""
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    membership = get_active_membership(session, small_group.id, member_id)
    if membership is None:
        raise ActiveMembershipNotFoundError
    if membership.role == role:
        return
    _ensure_leader_slot_free(session, small_group.id, role)
    _apply_role_change(session, membership, role, today)
    _commit_or_raise_conflict(session)


def set_small_group_leader(session: Session, small_group: SmallGroup, *, member_id: int, today: date) -> None:
    """Make the member the leader in one transaction, demoting any current leader to co-leader."""
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    if session.get(Member, member_id) is None:
        raise MemberNotFoundError
    current_leader = session.scalars(
        select(SmallGroupMember).where(
            SmallGroupMember.small_group_id == small_group.id,
            SmallGroupMember.role == SmallGroupRole.LEADER,
            SmallGroupMember.left_at.is_(None),
        )
    ).one_or_none()
    if current_leader is not None:
        if current_leader.member_id == member_id:
            return
        _apply_role_change(session, current_leader, SmallGroupRole.CO_LEADER, today)
        # Flush the demotion before the promotion so the active-leader index never sees two.
        session.flush()
    membership = get_active_membership(session, small_group.id, member_id)
    if membership is None:
        _add_membership(session, small_group.id, member_id, SmallGroupRole.LEADER, today)
    else:
        _apply_role_change(session, membership, SmallGroupRole.LEADER, today)
    _commit_or_raise_conflict(session)


def remove_small_group_member(
    session: Session, small_group: SmallGroup, *, member_id: int, today: date
) -> None:
    """End the member's current period; the row stays as history."""
    membership = get_active_membership(session, small_group.id, member_id)
    if membership is None:
        raise ActiveMembershipNotFoundError
    membership.left_at = today
    session.commit()


def _add_membership(
    session: Session, small_group_id: int, member_id: int, role: SmallGroupRole, today: date
) -> None:
    session.add(
        SmallGroupMember(small_group_id=small_group_id, member_id=member_id, role=role, joined_at=today)
    )


def _apply_role_change(
    session: Session, membership: SmallGroupMember, role: SmallGroupRole, today: date
) -> None:
    """Change an active membership's role, keeping history. Doesn't commit."""
    if membership.joined_at == today:
        # Started today: a closed zero-length period would be noise, so correct it in place.
        membership.role = role
        return
    membership.left_at = today
    # Inserts run before updates in a flush, so close the old period first or the partial
    # unique indexes (one active row per member/leader) would see both as active.
    session.flush()
    _add_membership(session, membership.small_group_id, membership.member_id, role, today)


def get_active_membership(session: Session, small_group_id: int, member_id: int) -> SmallGroupMember | None:
    """The member's open period in the group, if any."""
    return session.scalars(
        select(SmallGroupMember).where(
            SmallGroupMember.small_group_id == small_group_id,
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.left_at.is_(None),
        )
    ).one_or_none()


def _ensure_leader_slot_free(session: Session, small_group_id: int, role: SmallGroupRole) -> None:
    if role != SmallGroupRole.LEADER:
        return
    leader = session.scalars(
        select(SmallGroupMember.id).where(
            SmallGroupMember.small_group_id == small_group_id,
            SmallGroupMember.role == SmallGroupRole.LEADER,
            SmallGroupMember.left_at.is_(None),
        )
    ).first()
    if leader is not None:
        raise LeaderAlreadyExistsError


def _commit_or_raise_conflict(session: Session) -> None:
    """Commit, mapping a lost race on the partial unique indexes to the same errors as the checks."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        message = str(exc.orig)
        # Check the leader index first: the other index name is a prefix of it.
        if "uq_small_group_members_active_leader" in message:
            raise LeaderAlreadyExistsError from exc
        if "uq_small_group_members_active" in message:
            raise MemberAlreadyInGroupError from exc
        raise
