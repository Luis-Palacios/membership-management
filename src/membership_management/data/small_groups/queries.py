from collections.abc import Sequence
from datetime import date

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import aliased, joinedload, selectinload

from membership_management.data.guests.models import Guest
from membership_management.data.members.models import Member, MemberStatus
from membership_management.data.small_groups.models import (
    SmallGroup,
    SmallGroupMember,
    SmallGroupNoMeetingWeek,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupReportItem,
    SmallGroupReportItemPerson,
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
            SmallGroup.audience.label("audience"),
            SmallGroup.meeting_address.label("meeting_address"),
            SmallGroup.meeting_day.label("meeting_day"),
            SmallGroup.closed_at.label("closed_at"),
            # count(col) skips NULLs: a row is a member's or a guest's, never both.
            func.count(SmallGroupMember.member_id).label("active_member_count"),
            func.count(SmallGroupMember.guest_id).label("active_guest_count"),
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


def small_group_active_guests_query(small_group_id: int) -> Select:
    """The guests currently in the group (open periods only), by name."""
    return (
        select(
            Guest.id.label("guest_id"),
            Guest.name.label("guest_name"),
            SmallGroupMember.joined_at.label("joined_at"),
        )
        .join(Guest, Guest.id == SmallGroupMember.guest_id)
        .where(SmallGroupMember.small_group_id == small_group_id, SmallGroupMember.left_at.is_(None))
        .order_by(Guest.name, Guest.id)
    )


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
    """Membership periods, members' and guests', that cover `d` (reports rule 3: joined by then, not
    left before it).

    A member can appear twice when their role changed on `d`; the service picks one per person.
    """
    covers = and_(
        SmallGroupMember.small_group_id == small_group_id,
        SmallGroupMember.joined_at <= d,
        or_(SmallGroupMember.left_at.is_(None), SmallGroupMember.left_at >= d),
    )
    members = (
        select(
            Member.id.label("member_id"),
            cast(null(), Integer).label("guest_id"),
            Member.name.label("name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
            SmallGroupMember.left_at.label("left_at"),
            SmallGroupMember.id.label("period_id"),
        )
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(covers)
    )
    guests = (
        select(
            cast(null(), Integer).label("member_id"),
            Guest.id.label("guest_id"),
            Guest.name.label("name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
            SmallGroupMember.left_at.label("left_at"),
            SmallGroupMember.id.label("period_id"),
        )
        .join(Guest, Guest.id == SmallGroupMember.guest_id)
        .where(covers)
    )
    return select(union_all(members, guests).subquery())


def report_in_scope_query(report_id: int, only_group_ids: frozenset[int] | None) -> Select:
    """One report with what its detail needs; `only_group_ids` filters by group in SQL (None = all)."""
    query = (
        select(SmallGroupReport)
        .where(SmallGroupReport.id == report_id)
        .options(
            joinedload(SmallGroupReport.small_group),
            joinedload(SmallGroupReport.submitted_by),
            selectinload(SmallGroupReport.attendances).options(
                joinedload(SmallGroupReportAttendance.member), joinedload(SmallGroupReportAttendance.guest)
            ),
        )
    )
    if only_group_ids is not None:
        query = query.where(SmallGroupReport.small_group_id.in_(only_group_ids))
    return query


def report_on_date_query(small_group_id: int, d: date) -> Select:
    """The (id, held) of the group's report on `d`; at most one row (unique per group and date)."""
    return select(SmallGroupReport.id, SmallGroupReport.held).where(
        SmallGroupReport.small_group_id == small_group_id, SmallGroupReport.meeting_date == d
    )


def recent_attendance_marks_query(small_group_id: int, before: date, report_limit: int) -> Select:
    """Attendance rows of the group's latest `report_limit` held reports strictly before `before`, newest
    first. A no meeting has no attendance, so it must not take one of the window's slots."""
    latest_reports = (
        select(SmallGroupReport.id)
        .where(
            SmallGroupReport.small_group_id == small_group_id,
            SmallGroupReport.meeting_date < before,
            SmallGroupReport.held.is_(True),
        )
        .order_by(SmallGroupReport.meeting_date.desc())
        .limit(report_limit)
    )
    return (
        select(
            SmallGroupReportAttendance.member_id.label("member_id"),
            SmallGroupReportAttendance.guest_id.label("guest_id"),
            SmallGroupReportAttendance.attended_group.label("attended_group"),
        )
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportAttendance.report_id)
        .where(SmallGroupReportAttendance.report_id.in_(latest_reports))
        .order_by(SmallGroupReport.meeting_date.desc())
    )


def guests_last_attended_query(guest_ids: Sequence[int]) -> Select:
    """The newest meeting date each guest attended (in any group); guests who never did have no row."""
    return (
        select(
            SmallGroupReportAttendance.guest_id.label("guest_id"),
            func.max(SmallGroupReport.meeting_date).label("last_attended_date"),
        )
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportAttendance.report_id)
        .where(
            SmallGroupReportAttendance.guest_id.in_(guest_ids),
            SmallGroupReportAttendance.attended_group.is_(True),
        )
        .group_by(SmallGroupReportAttendance.guest_id)
    )


def active_guest_period_query(guest_id: int) -> Select:
    """The guest's open period, with its group's name (a guest has at most one: the partial unique index)."""
    return (
        select(SmallGroupMember, SmallGroup.name)
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.guest_id == guest_id, SmallGroupMember.left_at.is_(None))
    )


def latest_guest_report_date_query(small_group_id: int, guest_id: int) -> Select:
    """Meeting date of the group's newest report that has an attendance row for the guest."""
    return (
        select(func.max(SmallGroupReport.meeting_date))
        .join(SmallGroupReportAttendance, SmallGroupReportAttendance.report_id == SmallGroupReport.id)
        .where(
            SmallGroupReport.small_group_id == small_group_id, SmallGroupReportAttendance.guest_id == guest_id
        )
    )


def report_groups_query(only_ids: frozenset[int] | None, small_group_id: int | None = None) -> Select:
    """The groups a report list or summary is about, optionally one group; scope filtered in SQL."""
    query = select(
        SmallGroup.id.label("id"),
        SmallGroup.name.label("name"),
        SmallGroup.audience.label("audience"),
        SmallGroup.meeting_day.label("meeting_day"),
        SmallGroup.closed_at.label("closed_at"),
    ).order_by(SmallGroup.name, SmallGroup.id)
    if only_ids is not None:
        query = query.where(SmallGroup.id.in_(only_ids))
    if small_group_id is not None:
        query = query.where(SmallGroup.id == small_group_id)
    return query


def filed_reports_query(
    only_group_ids: frozenset[int] | None,
    *,
    small_group_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    report_ids: Select | None = None,
) -> Select:
    """Filed reports with their submitter and three attendance counts (no observations)."""
    attendance = SmallGroupReportAttendance
    query = (
        select(
            SmallGroupReport.id.label("id"),
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroup.audience.label("small_group_audience"),
            SmallGroup.closed_at.label("small_group_closed_at"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            Member.id.label("submitted_by_member_id"),
            Member.name.label("submitted_by_name"),
            SmallGroupReport.submitted_at.label("submitted_at"),
            SmallGroupReport.held.label("held"),
            SmallGroupReport.not_held_reason.label("not_held_reason"),
            func.count(attendance.id).label("roster_count"),
            func.count(attendance.id)
            .filter(attendance.attended_group.is_(True))
            .label("attended_group_count"),
            func.count(attendance.id)
            .filter(attendance.attended_church.is_(True))
            .label("attended_church_count"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .join(Member, Member.id == SmallGroupReport.submitted_by_member_id)
        .outerjoin(attendance, attendance.report_id == SmallGroupReport.id)
        .group_by(SmallGroupReport.id, SmallGroup.id, Member.id)
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroup.name, SmallGroupReport.id)
    )
    if only_group_ids is not None:
        query = query.where(SmallGroupReport.small_group_id.in_(only_group_ids))
    if small_group_id is not None:
        query = query.where(SmallGroupReport.small_group_id == small_group_id)
    if from_date is not None:
        query = query.where(SmallGroupReport.meeting_date >= from_date)
    if to_date is not None:
        query = query.where(SmallGroupReport.meeting_date <= to_date)
    if report_ids is not None:
        query = query.where(SmallGroupReport.id.in_(report_ids))
    return query


def report_dates_query(group_ids: frozenset[int], from_date: date, to_date: date) -> Select:
    """(report, group, meeting date, held) of every report in the range, no meetings included on
    purpose: a date with a no meeting is filed for rule 10, just not a held meeting."""
    return select(
        SmallGroupReport.id.label("report_id"),
        SmallGroupReport.small_group_id.label("small_group_id"),
        SmallGroupReport.meeting_date.label("meeting_date"),
        SmallGroupReport.held.label("held"),
    ).where(
        SmallGroupReport.small_group_id.in_(group_ids),
        SmallGroupReport.meeting_date >= from_date,
        SmallGroupReport.meeting_date <= to_date,
    )


def leadership_periods_query(group_ids: frozenset[int]) -> Select:
    """Leader and co-leader periods of the groups, for "did the group have a leader that day"."""
    return select(
        SmallGroupMember.small_group_id.label("small_group_id"),
        SmallGroupMember.joined_at.label("joined_at"),
        SmallGroupMember.left_at.label("left_at"),
    ).where(
        SmallGroupMember.small_group_id.in_(group_ids),
        SmallGroupMember.role.in_([SmallGroupRole.LEADER, SmallGroupRole.CO_LEADER]),
    )


def latest_report_ids_query(group_ids: frozenset[int]) -> Select:
    """The id of each group's newest held report (by meeting date); a no meeting is never the last report."""
    ranked = (
        select(
            SmallGroupReport.id.label("id"),
            func.row_number()
            .over(
                partition_by=SmallGroupReport.small_group_id,
                order_by=(SmallGroupReport.meeting_date.desc(), SmallGroupReport.id.desc()),
            )
            .label("rank"),
        )
        .where(SmallGroupReport.small_group_id.in_(group_ids), SmallGroupReport.held.is_(True))
        .subquery()
    )
    return select(ranked.c.id).where(ranked.c.rank == 1)


def member_active_roles_query(member_id: int, group_ids: frozenset[int]) -> Select:
    """The member's current role in each of the groups (open periods only)."""
    return select(
        SmallGroupMember.small_group_id.label("small_group_id"), SmallGroupMember.role.label("role")
    ).where(
        SmallGroupMember.member_id == member_id,
        SmallGroupMember.small_group_id.in_(group_ids),
        SmallGroupMember.left_at.is_(None),
    )


def week_reports_query(group_ids: frozenset[int], from_date: date, to_date: date) -> Select:
    """The groups' reports dated in [from_date, to_date] with attendance counts, newest first. Counts
    only: the observation text is never selected (rule 9), just how many rows have one."""
    attendance = SmallGroupReportAttendance
    return (
        select(
            SmallGroupReport.id.label("id"),
            SmallGroupReport.small_group_id.label("small_group_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            func.count(attendance.id).label("roster_count"),
            func.count(attendance.id)
            .filter(attendance.attended_group.is_(True))
            .label("attended_group_count"),
            func.count(attendance.id)
            .filter(attendance.attended_church.is_(True))
            .label("attended_church_count"),
            func.count(attendance.id).filter(attendance.observation.is_not(None)).label("observation_count"),
            Member.id.label("submitted_by_member_id"),
            Member.name.label("submitted_by_name"),
            SmallGroupReport.held.label("held"),
            SmallGroupReport.not_held_reason.label("not_held_reason"),
        )
        .join(Member, Member.id == SmallGroupReport.submitted_by_member_id)
        .outerjoin(attendance, attendance.report_id == SmallGroupReport.id)
        .where(
            SmallGroupReport.small_group_id.in_(group_ids),
            SmallGroupReport.meeting_date >= from_date,
            SmallGroupReport.meeting_date <= to_date,
        )
        .group_by(SmallGroupReport.id, Member.id)
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroupReport.id.desc())
    )


def reported_group_ids_in_week_query(group_ids: frozenset[int], from_date: date, to_date: date) -> Select:
    """The groups with any report dated in [from_date, to_date], held or not."""
    return (
        select(SmallGroupReport.small_group_id)
        .where(
            SmallGroupReport.small_group_id.in_(group_ids),
            SmallGroupReport.meeting_date >= from_date,
            SmallGroupReport.meeting_date <= to_date,
        )
        .distinct()
    )


def no_meeting_week_query(*, week_id: int | None = None, week_start: date | None = None) -> Select:
    """A church-wide no meeting week, by id or by week start, with its creator's name and how many
    reports are still linked to it."""
    linked_count = (
        select(func.count())
        .where(SmallGroupReport.no_meeting_week_id == SmallGroupNoMeetingWeek.id)
        .scalar_subquery()
    )
    query = select(
        SmallGroupNoMeetingWeek.id.label("id"),
        SmallGroupNoMeetingWeek.week_start.label("week_start"),
        SmallGroupNoMeetingWeek.reason.label("reason"),
        Member.id.label("created_by_member_id"),
        Member.name.label("created_by_name"),
        SmallGroupNoMeetingWeek.created_at.label("created_at"),
        SmallGroupNoMeetingWeek.updated_at.label("updated_at"),
        linked_count.label("linked_count"),
    ).join(Member, Member.id == SmallGroupNoMeetingWeek.created_by_member_id)
    if week_id is not None:
        query = query.where(SmallGroupNoMeetingWeek.id == week_id)
    if week_start is not None:
        query = query.where(SmallGroupNoMeetingWeek.week_start == week_start)
    return query


def active_leaders_query(group_ids: frozenset[int]) -> Select:
    """Who leads or co-leads each group today (open periods), leader first, then co-leaders by name."""
    return (
        select(
            SmallGroupMember.small_group_id.label("small_group_id"),
            Member.id.label("member_id"),
            Member.name.label("member_name"),
            SmallGroupMember.role.label("role"),
        )
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(
            SmallGroupMember.small_group_id.in_(group_ids),
            SmallGroupMember.role.in_([SmallGroupRole.LEADER, SmallGroupRole.CO_LEADER]),
            SmallGroupMember.left_at.is_(None),
        )
        .order_by(
            # 'co_leader' < 'leader' alphabetically, so sort the leader explicitly first.
            (SmallGroupMember.role != SmallGroupRole.LEADER),
            Member.name,
            Member.id,
        )
    )


def shared_reports_query(group_ids: frozenset[int], from_date: date, to_date: date) -> Select:
    """The groups' held reports dated in [from_date, to_date] (prayer & follow-up rule 6), oldest
    meeting first, then group name. Their items are loaded apart; no-meeting reports have none."""
    return (
        select(
            SmallGroupReport.id.label("report_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroup.audience.label("small_group_audience"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .where(
            SmallGroupReport.small_group_id.in_(group_ids),
            SmallGroupReport.held.is_(True),
            SmallGroupReport.meeting_date >= from_date,
            SmallGroupReport.meeting_date <= to_date,
        )
        .order_by(SmallGroupReport.meeting_date, SmallGroup.name, SmallGroupReport.id)
    )


def report_items_query(report_ids: frozenset[int]) -> Select:
    """The reports' items, by report, then section order (prayer, praise, follow-up), then position."""
    section_order = case(
        {"prayer": 0, "praise": 1, "followUp": 2}, value=SmallGroupReportItem.section, else_=3
    )
    return (
        select(
            SmallGroupReportItem.id.label("id"),
            SmallGroupReportItem.report_id.label("report_id"),
            SmallGroupReportItem.section.label("section"),
            SmallGroupReportItem.text.label("text"),
        )
        .where(SmallGroupReportItem.report_id.in_(report_ids))
        .order_by(SmallGroupReportItem.report_id, section_order, SmallGroupReportItem.position)
    )


def report_tagged_people_query(report_id: int) -> Select:
    """Who the report's items tag, by section (one row per item and person)."""
    return (
        select(
            SmallGroupReportItem.section.label("section"),
            SmallGroupReportItemPerson.member_id.label("member_id"),
            SmallGroupReportItemPerson.guest_id.label("guest_id"),
        )
        .join(SmallGroupReportItem, SmallGroupReportItem.id == SmallGroupReportItemPerson.item_id)
        .where(SmallGroupReportItem.report_id == report_id)
    )


def people_current_groups_query(member_ids: frozenset[int], guest_ids: frozenset[int]) -> Select:
    """The open groups these members and guests are active in today, with their role, by group name."""
    return (
        select(
            SmallGroupMember.member_id.label("member_id"),
            SmallGroupMember.guest_id.label("guest_id"),
            SmallGroup.id.label("id"),
            SmallGroup.name.label("name"),
            SmallGroup.audience.label("audience"),
            SmallGroupMember.role.label("role"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(
            or_(SmallGroupMember.member_id.in_(member_ids), SmallGroupMember.guest_id.in_(guest_ids)),
            SmallGroupMember.left_at.is_(None),
            SmallGroup.closed_at.is_(None),
        )
        .order_by(SmallGroup.name, SmallGroup.id)
    )


def people_query(member_ids: frozenset[int], guest_ids: frozenset[int]) -> Select:
    """Name and inactive flag of each of these members and guests that exists (guests never inactive)."""
    members = select(
        literal("member").label("kind"),
        Member.id.label("id"),
        Member.name.label("name"),
        (Member.status == MemberStatus.INACTIVE).label("inactive"),
    ).where(Member.id.in_(member_ids))
    guests = select(
        literal("guest").label("kind"),
        Guest.id.label("id"),
        Guest.name.label("name"),
        false().label("inactive"),
    ).where(Guest.id.in_(guest_ids))
    return select(union_all(members, guests).subquery())
