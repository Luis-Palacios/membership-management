from datetime import date

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import aliased, joinedload, selectinload

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)


def list_small_groups_query(only_ids: frozenset[int] | None = None) -> Select:
    """All groups, or only `only_ids` when given (the scope filter is applied in SQL)."""
    # The partial unique index allows at most one active leader row per group, so joining it
    # next to the active-member join can't change the count; its columns just join the GROUP BY.
    leader = aliased(SmallGroupMember)
    leader_member = aliased(Member)
    query = (
        select(
            SmallGroup.id.label("id"),
            SmallGroup.name.label("name"),
            SmallGroup.meeting_address.label("meeting_address"),
            SmallGroup.meeting_day.label("meeting_day"),
            SmallGroup.closed_at.label("closed_at"),
            func.count(SmallGroupMember.id).label("active_member_count"),
            leader_member.id.label("leader_member_id"),
            leader_member.name.label("leader_name"),
        )
        .outerjoin(
            SmallGroupMember,
            and_(SmallGroupMember.small_group_id == SmallGroup.id, SmallGroupMember.left_at.is_(None)),
        )
        .outerjoin(
            leader,
            and_(
                leader.small_group_id == SmallGroup.id,
                leader.role == SmallGroupRole.LEADER,
                leader.left_at.is_(None),
            ),
        )
        .outerjoin(leader_member, leader_member.id == leader.member_id)
        .group_by(SmallGroup.id, leader_member.id)
        .order_by(SmallGroup.name, SmallGroup.id)
    )
    if only_ids is not None:
        query = query.where(SmallGroup.id.in_(only_ids))
    return query


def small_group_active_members_query(small_group_id: int) -> Select:
    """The members currently in the group (open membership periods only)."""
    return (
        select(
            Member.id.label("member_id"),
            Member.name.label("member_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
        )
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(SmallGroupMember.small_group_id == small_group_id, SmallGroupMember.left_at.is_(None))
        .order_by(Member.name, Member.id)
    )


def leads_in_scope_condition() -> ColumnElement[bool]:
    """Filter on `small_group_members` joined to `small_groups`: leader/co-leader periods that count.

    Active periods, or periods ended by the group closing (`left_at >= closed_at`, since closing
    ends every active period on the close date). A leader who left before the close doesn't match.
    """
    return and_(
        SmallGroupMember.role.in_([SmallGroupRole.LEADER, SmallGroupRole.CO_LEADER]),
        or_(SmallGroupMember.left_at.is_(None), SmallGroupMember.left_at >= SmallGroup.closed_at),
    )


def led_small_group_ids_query(member_id: int) -> Select:
    """Ids of the groups the member leads or co-led when they closed (the access scope)."""
    return (
        select(SmallGroup.id)
        .join(SmallGroupMember, SmallGroupMember.small_group_id == SmallGroup.id)
        .where(SmallGroupMember.member_id == member_id, leads_in_scope_condition())
        .distinct()
    )


def roster_periods_on_date_query(small_group_id: int, d: date) -> Select:
    """Membership periods that cover `d` (rule 3: joined by then, not left before it).

    A member can appear twice when their role changed on `d`; the service picks one per member.
    """
    return (
        select(
            Member.id.label("member_id"),
            Member.name.label("member_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
            SmallGroupMember.left_at.label("left_at"),
            SmallGroupMember.id.label("period_id"),
        )
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(
            SmallGroupMember.small_group_id == small_group_id,
            SmallGroupMember.joined_at <= d,
            or_(SmallGroupMember.left_at.is_(None), SmallGroupMember.left_at >= d),
        )
    )


def report_in_scope_query(report_id: int, only_group_ids: frozenset[int] | None) -> Select:
    """One report with what its detail needs; `only_group_ids` filters by group in SQL (None = all)."""
    query = (
        select(SmallGroupReport)
        .where(SmallGroupReport.id == report_id)
        .options(
            joinedload(SmallGroupReport.small_group),
            joinedload(SmallGroupReport.submitted_by),
            selectinload(SmallGroupReport.attendances).joinedload(SmallGroupReportAttendance.member),
        )
    )
    if only_group_ids is not None:
        query = query.where(SmallGroupReport.small_group_id.in_(only_group_ids))
    return query


def report_id_on_date_query(small_group_id: int, d: date) -> Select:
    return select(SmallGroupReport.id).where(
        SmallGroupReport.small_group_id == small_group_id, SmallGroupReport.meeting_date == d
    )


def recent_attendance_marks_query(small_group_id: int, before: date, report_limit: int) -> Select:
    """Attendance rows of the group's latest `report_limit` reports strictly before `before`, newest first."""
    latest_reports = (
        select(SmallGroupReport.id)
        .where(SmallGroupReport.small_group_id == small_group_id, SmallGroupReport.meeting_date < before)
        .order_by(SmallGroupReport.meeting_date.desc())
        .limit(report_limit)
    )
    return (
        select(
            SmallGroupReportAttendance.member_id.label("member_id"),
            SmallGroupReportAttendance.attended_group.label("attended_group"),
        )
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportAttendance.report_id)
        .where(SmallGroupReportAttendance.report_id.in_(latest_reports))
        .order_by(SmallGroupReport.meeting_date.desc())
    )
