import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member
from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.models import (
    ReportConversation,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)
from membership_management.data.small_groups.queries import (
    active_leaders_query,
    filed_reports_query,
    latest_report_ids_query,
    leadership_periods_query,
    led_small_group_ids_query,
    list_small_groups_query,
    member_active_roles_query,
    recent_attendance_marks_query,
    report_dates_query,
    report_groups_query,
    report_in_scope_query,
    report_on_date_query,
    roster_periods_on_date_query,
    shared_reports_query,
    small_group_active_members_query,
    week_reports_query,
)
from membership_management.data.small_groups.results import (
    ActiveLeaderRow,
    AttendanceMark,
    FiledReportRow,
    GroupReportSummary,
    GroupRole,
    LeadershipPeriod,
    NotFiledMeeting,
    RecentMeeting,
    ReportAttendanceView,
    ReportCounts,
    ReportDate,
    ReportDetail,
    ReportGroupRow,
    ReportInput,
    ReportPage,
    ReportRoster,
    ReportShared,
    ReportWeek,
    RosterPeriod,
    RosterPerson,
    SharedEntry,
    SharedReportRow,
    SmallGroupActiveMember,
    SmallGroupSummary,
    StillToReport,
    WeekGroup,
    WeekLeader,
    WeekReportRow,
    WeekStatus,
)

# Reports looked at for a "missed the last N meetings" hint (rule 11); plenty for a hint.
MISSED_STREAK_REPORT_WINDOW = 12
# How far back a meeting without a report still counts as "not filed" (rule 10).
NOT_FILED_WINDOW_DAYS = 28

ReportStatus = Literal["all", "filed", "notHeld", "notFiled"]


class SmallGroupAlreadyClosedError(Exception):
    """The group already has a closed_at date."""


class SmallGroupClosedError(Exception):
    """The group is closed, so its memberships can't change."""


class MemberNotFoundError(Exception):
    """No member with the given ID exists."""


class MemberAlreadyInGroupError(Exception):
    """The member already has an active membership in the group."""


class JoinedInFutureError(Exception):
    """The join date is after today."""


class MembershipOverlapError(Exception):
    """The join date falls inside one of the member's earlier periods in the group."""


class ActiveMembershipNotFoundError(Exception):
    """The member has no active membership in the group."""


class LeaderAlreadyExistsError(Exception):
    """The group already has an active leader."""


class ReportAlreadyExistsError(Exception):
    """The group already has a report for that meeting date (rule 1)."""

    def __init__(self, existing_id: int, existing_held: bool) -> None:
        super().__init__(existing_id)
        self.existing_id = existing_id
        self.existing_held = existing_held


class ReportKindChangeError(Exception):
    """An edit would turn a meeting into a no meeting or back, or asked to replace one (rule 13)."""


class MemberRequiredToSubmitError(Exception):
    """The caller has no linked member, and submitting a report needs one (rule 5)."""


class FutureMeetingDateError(Exception):
    """The meeting date is after today in the church's time zone (rule 2)."""


class AttendanceMismatchError(Exception):
    """The attendance rows don't match the group's members on the meeting date (rule 3)."""


class NotGroupLeaderOnDateError(Exception):
    """A scoped caller didn't hold leader or co-leader in the group on the meeting date (rule 5)."""


class FutureWeekError(Exception):
    """The requested week starts after the current church week (groups dashboard rule 4)."""


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
    existing = session.execute(report_on_date_query(small_group.id, d)).one_or_none()
    return ReportRoster(
        people=[p._replace(missed_streak=streaks[p.member_id]) for p in people],
        existing_report_id=existing[0] if existing is not None else None,
        existing_report_held=existing[1] if existing is not None else None,
    )


def get_report(
    session: Session, report_id: int, only_group_ids: frozenset[int] | None
) -> SmallGroupReport | None:
    """The report, or None when it doesn't exist or its group is outside `only_group_ids`."""
    if only_group_ids is not None and not only_group_ids:
        return None
    return session.scalars(report_in_scope_query(report_id, only_group_ids)).one_or_none()


def observations_visible_to(*, sees_all_observations: bool, leads_group: bool) -> bool:
    """Rule 9: `sees_all_observations` (`smallGroupReports: viewObservations`), and the group's leaders."""
    return sees_all_observations or leads_group


def build_report_detail(
    session: Session, report: SmallGroupReport, *, sees_all_observations: bool, leads_group: bool
) -> ReportDetail:
    """The report as a viewer may see it; rule 9 is decided once, here, and carried in the result."""
    observations_visible = observations_visible_to(
        sees_all_observations=sees_all_observations, leads_group=leads_group
    )
    roster = {p.member_id: p for p in roster_on_date(session, report.small_group_id, report.meeting_date)}
    streaks = missed_streaks(
        session, report.small_group_id, [a.member_id for a in report.attendances], report.meeting_date
    )
    views = [
        ReportAttendanceView(
            member_id=a.member_id,
            member_name=a.member.name,
            # Memberships edited after the report could drop someone from the roster: show a member.
            role=roster[a.member_id].role if a.member_id in roster else SmallGroupRole.MEMBER,
            joined_at=roster[a.member_id].joined_at if a.member_id in roster else None,
            attended_group=a.attended_group,
            attended_church=a.attended_church,
            missed_streak=streaks[a.member_id],
            observation=a.observation if observations_visible else None,
        )
        for a in report.attendances
    ]
    views.sort(key=lambda v: (_ROLE_ORDER[v.role], v.member_name, v.member_id))
    return ReportDetail(
        id=report.id,
        small_group_id=report.small_group_id,
        small_group_name=report.small_group.name,
        small_group_meeting_address=report.small_group.meeting_address,
        small_group_closed_at=report.small_group.closed_at,
        meeting_date=report.meeting_date,
        address=report.address,
        group_prayer_request=report.group_prayer_request,
        group_praise_report=report.group_praise_report,
        group_relevant_discussion=report.group_relevant_discussion,
        submitted_by_member_id=report.submitted_by_member_id,
        submitted_by_name=report.submitted_by.name,
        submitted_at=report.submitted_at,
        observations_visible=observations_visible,
        attendances=views,
        held=report.held,
        not_held_reason=report.not_held_reason,
        conversation_count=session.scalar(
            select(func.count())
            .select_from(ReportConversation)
            .where(ReportConversation.report_id == report.id)
        )
        or 0,
    )


def create_report(
    session: Session,
    small_group: SmallGroup,
    body: ReportInput,
    *,
    submitter_member_id: int,
    caller_is_scoped: bool,
    today: date,
) -> SmallGroupReport:
    replaced = _validate_date(
        session,
        small_group,
        body.meeting_date,
        today=today,
        ignore_report_id=None,
        replaces_no_meeting=body.replaces_no_meeting and body.held,
    )
    roster = _validated_roster(session, small_group, body)
    if caller_is_scoped and not any(
        p.member_id == submitter_member_id and p.role != SmallGroupRole.MEMBER for p in roster
    ):
        raise NotGroupLeaderOnDateError
    report = SmallGroupReport(
        small_group_id=small_group.id,
        meeting_date=body.meeting_date,
        held=body.held,
        not_held_reason=body.not_held_reason,
        address=body.address,
        group_prayer_request=body.group_prayer_request,
        group_praise_report=body.group_praise_report,
        group_relevant_discussion=body.group_relevant_discussion,
        submitted_by_member_id=submitter_member_id,
        attendances=[
            SmallGroupReportAttendance(
                member_id=a.member_id,
                attended_group=a.attended_group,
                attended_church=a.attended_church,
                observation=a.observation,
            )
            for a in body.attendances
        ],
    )
    if replaced is not None:
        # Flush the delete first: the unit of work would otherwise insert before deleting and
        # trip the (group, meeting date) unique constraint.
        session.delete(replaced)
        session.flush()
    session.add(report)
    _commit_report_or_raise_conflict(session, small_group.id, body.meeting_date)
    return report


def update_report(
    session: Session,
    report: SmallGroupReport,
    body: ReportInput,
    *,
    sees_all_observations: bool,
    leads_group: bool,
    today: date,
) -> SmallGroupReport:
    """Replace the report's content (rule 6: `submitted_by_member_id` and `submitted_at` never change).

    Attendance rows are updated in place by member so stored observations survive. A caller who
    can't see observations (rule 9) can't change them either: theirs are ignored, stored ones kept.
    """
    if body.held != report.held or body.replaces_no_meeting:
        raise ReportKindChangeError
    _validate_date(
        session,
        report.small_group,
        body.meeting_date,
        today=today,
        ignore_report_id=report.id,
        replaces_no_meeting=False,
    )
    if not report.held:
        report.meeting_date = body.meeting_date
        report.not_held_reason = body.not_held_reason
        _commit_report_or_raise_conflict(session, report.small_group_id, body.meeting_date)
        return report
    _validated_roster(session, report.small_group, body)
    may_edit_observations = observations_visible_to(
        sees_all_observations=sees_all_observations, leads_group=leads_group
    )
    report.meeting_date = body.meeting_date
    report.address = body.address
    report.group_prayer_request = body.group_prayer_request
    report.group_praise_report = body.group_praise_report
    report.group_relevant_discussion = body.group_relevant_discussion
    sent = {a.member_id: a for a in body.attendances}
    existing = {row.member_id: row for row in report.attendances}
    for member_id, row in existing.items():
        if member_id not in sent:
            report.attendances.remove(row)  # delete-orphan removes the row
    for member_id, attendance in sent.items():
        row = existing.get(member_id)
        if row is None:
            report.attendances.append(
                SmallGroupReportAttendance(
                    member_id=member_id,
                    attended_group=attendance.attended_group,
                    attended_church=attendance.attended_church,
                    observation=attendance.observation if may_edit_observations else None,
                )
            )
            continue
        row.attended_group = attendance.attended_group
        row.attended_church = attendance.attended_church
        if may_edit_observations:
            row.observation = attendance.observation
    _commit_report_or_raise_conflict(session, report.small_group_id, body.meeting_date)
    return report


def delete_report(session: Session, report: SmallGroupReport) -> None:
    """Delete the report; its attendance rows go with it (rule 8: not when the group is closed)."""
    if report.small_group.closed_at is not None:
        raise SmallGroupClosedError
    session.delete(report)
    session.commit()


def _fold(text: str) -> str:
    """Lowercase and drop accents, so "jovenes" finds "Jóvenes"."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _leadership_by_group(session: Session, group_ids: frozenset[int]) -> dict[int, list[LeadershipPeriod]]:
    leadership: dict[int, list[LeadershipPeriod]] = {}
    for period in all_as(session, leadership_periods_query(group_ids), LeadershipPeriod):
        leadership.setdefault(period.small_group_id, []).append(period)
    return leadership


def recent_meetings(
    session: Session,
    groups: Sequence[ReportGroupRow],
    start: date,
    end: date,
    leadership: dict[int, list[LeadershipPeriod]] | None = None,
) -> dict[int, list[RecentMeeting]]:
    """Rule 10's candidate meetings, per open group with a meeting day: newest first, every date in
    [start, end] that falls on that weekday and had a leader or co-leader that day, with the id of the
    report filed in its church week, any weekday (None = not filed); a held report beats a no meeting.
    Closed groups get none (they can't take a report, rule 8), nor do groups without a meeting day.
    `end` is the caller's "yesterday" at the latest: today never counts. Pass `leadership` (from
    `_leadership_by_group`) when the caller already loaded it.
    """
    candidates = [g for g in groups if g.closed_at is None and g.meeting_day is not None]
    meetings: dict[int, list[RecentMeeting]] = {g.id: [] for g in candidates}
    if not candidates or start > end:
        return meetings
    ids = frozenset(g.id for g in candidates)
    # A report anywhere in the church week (Sunday to Saturday) files that week's meeting, the same
    # test the groups dashboard uses (its rule 6), so look at whole weeks around [start, end].
    filed: dict[tuple[int, date], ReportDate] = {}
    for r in all_as(
        session,
        report_dates_query(ids, church_sunday(start), church_sunday(end) + timedelta(days=6)),
        ReportDate,
    ):
        key = (r.small_group_id, church_sunday(r.meeting_date))
        if key not in filed or (r.held and not filed[key].held):
            filed[key] = r
    if leadership is None:
        leadership = _leadership_by_group(session, ids)
    for group in candidates:
        day = start
        while day <= end:
            if day.isoweekday() == group.meeting_day and any(
                p.joined_at <= day and (p.left_at is None or p.left_at >= day)
                for p in leadership.get(group.id, [])
            ):
                report = filed.get((group.id, church_sunday(day)))
                meetings[group.id].append(
                    RecentMeeting(day, report.report_id if report else None, report.held if report else None)
                )
            day += timedelta(days=1)
        meetings[group.id].reverse()
    return meetings


def not_filed_dates(
    session: Session, groups: Sequence[ReportGroupRow], start: date, end: date
) -> dict[int, list[date]]:
    """Rule 10: `recent_meetings` without a report, as dates."""
    return {
        group_id: [m.date for m in meetings if m.report_id is None]
        for group_id, meetings in recent_meetings(session, groups, start, end).items()
    }


def list_reports(
    session: Session,
    *,
    only_group_ids: frozenset[int] | None,
    small_group_id: int | None,
    from_date: date,
    to_date: date,
    status: ReportStatus,
    q: str | None,
    page: int,
    page_size: int,
    today: date,
) -> ReportPage:
    """Filed reports and not-filed meetings of the groups in scope, newest first, one page of them.

    `counts` ignore `status` (they feed the status filter); `total` is after it. `q` matches the group
    or, for filed reports, the submitter or a no meeting's reason, ignoring case and accents.
    """
    if only_group_ids is not None and not only_group_ids:
        return ReportPage(items=[], counts=ReportCounts(0, 0, 0, 0), total=0)
    filed = all_as(
        session,
        filed_reports_query(
            only_group_ids, small_group_id=small_group_id, from_date=from_date, to_date=to_date
        ),
        FiledReportRow,
    )
    groups = all_as(session, report_groups_query(only_group_ids, small_group_id), ReportGroupRow)
    missing = not_filed_dates(
        session,
        groups,
        max(from_date, today - timedelta(days=NOT_FILED_WINDOW_DAYS)),
        min(to_date, today - timedelta(days=1)),
    )
    not_filed = [
        NotFiledMeeting(g.id, g.name, g.closed_at, day) for g in groups for day in missing.get(g.id, [])
    ]
    if q is not None and q.strip():
        needle = _fold(q.strip())
        filed = [
            r
            for r in filed
            if needle in _fold(r.small_group_name)
            or needle in _fold(r.submitted_by_name)
            or needle in _fold(r.not_held_reason or "")
        ]
        not_filed = [m for m in not_filed if needle in _fold(m.small_group_name)]
    held = [r for r in filed if r.held]
    not_held = [r for r in filed if not r.held]
    counts = ReportCounts(
        all=len(filed) + len(not_filed), filed=len(held), not_held=len(not_held), not_filed=len(not_filed)
    )
    items: list[FiledReportRow | NotFiledMeeting] = []
    if status in ("all", "filed"):
        items.extend(held)
    if status in ("all", "notHeld"):
        items.extend(not_held)
    if status in ("all", "notFiled"):
        items.extend(not_filed)
    # Two stable passes: group name ascending inside each date, newest date first.
    items.sort(key=lambda item: item.small_group_name.casefold())
    items.sort(key=lambda item: item.meeting_date, reverse=True)
    start = (page - 1) * page_size
    return ReportPage(items=items[start : start + page_size], counts=counts, total=len(items))


def get_report_summary(
    session: Session,
    *,
    only_group_ids: frozenset[int] | None,
    member_id: int | None,
    today: date,
) -> list[GroupReportSummary]:
    """Per open group in scope: newest report, rule 10's recent meetings and whether anyone leads today.

    `role` is the caller's current role in the group for scoped callers (pass `only_group_ids`); full
    callers get None.
    """
    if only_group_ids is not None and not only_group_ids:
        return []
    groups = [
        g for g in all_as(session, report_groups_query(only_group_ids), ReportGroupRow) if g.closed_at is None
    ]
    if not groups:
        return []
    ids = frozenset(g.id for g in groups)
    latest = {
        r.small_group_id: r
        for r in all_as(
            session, filed_reports_query(None, report_ids=latest_report_ids_query(ids)), FiledReportRow
        )
    }
    roles: dict[int, SmallGroupRole] = {}
    if only_group_ids is not None and member_id is not None:
        roles = {
            r.small_group_id: r.role
            for r in all_as(session, member_active_roles_query(member_id, ids), GroupRole)
        }
    leadership = _leadership_by_group(session, ids)
    meetings = recent_meetings(
        session, groups, today - timedelta(days=NOT_FILED_WINDOW_DAYS), today - timedelta(days=1), leadership
    )
    return [
        GroupReportSummary(
            group=g,
            role=roles.get(g.id),
            last_report=latest.get(g.id),
            not_filed_dates=[m.date for m in meetings.get(g.id, []) if m.report_id is None],
            has_leader=any(p.left_at is None for p in leadership.get(g.id, [])),
            recent_meetings=meetings.get(g.id, []),
        )
        for g in groups
    ]


def get_report_week(session: Session, *, day: date, today: date) -> ReportWeek:
    """Every open group's status for the Sunday-to-Saturday week containing `day` (dashboard rule 6).

    A week after the current one is refused; any later day of the current week is the same week. Only
    counts of observations are read (rule 9), so the caller must be a full role.
    """
    week_start, week_end, is_current_week = _week_bounds(day, today)
    groups = _open_report_groups(session, None)
    if not groups:
        return ReportWeek(week_start, week_end, today, is_current_week, [])
    leaders = _active_leaders_by_group(session, frozenset(g.id for g in groups))
    return ReportWeek(
        week_start=week_start,
        week_end=week_end,
        today=today,
        is_current_week=is_current_week,
        groups=_week_groups(session, groups, week_start, today, leaders),
    )


def get_report_shared(
    session: Session, *, day: date, today: date, only_group_ids: frozenset[int] | None
) -> ReportShared:
    """The three group texts of every held report in the week containing `day`, for the open groups
    in scope, and the groups still to report (prayer & follow-up rules 5-11). Same week rules as
    `get_report_week`."""
    week_start, week_end, is_current_week = _week_bounds(day, today)
    groups = _open_report_groups(session, only_group_ids)
    if not groups:
        return ReportShared(week_start, week_end, today, is_current_week, [], [])
    ids = frozenset(g.id for g in groups)
    leaders = _active_leaders_by_group(session, ids)
    entries = [
        SharedEntry(
            report_id=r.report_id,
            meeting_date=r.meeting_date,
            small_group_id=r.small_group_id,
            small_group_name=r.small_group_name,
            leaders=leaders.get(r.small_group_id, []),
            prayer=_trimmed(r.group_prayer_request),
            praise=_trimmed(r.group_praise_report),
            follow_up=_trimmed(r.group_relevant_discussion),
        )
        for r in all_as(session, shared_reports_query(ids, week_start, week_end), SharedReportRow)
    ]
    still_to_report: list[StillToReport] = []
    for g in _week_groups(session, groups, week_start, today, leaders):
        match g.status:
            # These statuses always have the week's meeting date.
            case "notFiled" | "today" | "upcoming" if g.meeting_date is not None:
                still_to_report.append(StillToReport(g.group, g.status, g.meeting_date))
    # Rule 11, in the week view's order. Groups come by name and the sort is stable.
    still_to_report.sort(key=lambda g: ("notFiled", "today", "upcoming").index(g.status))
    return ReportShared(week_start, week_end, today, is_current_week, entries, still_to_report)


def _trimmed(text: str | None) -> str | None:
    return (text.strip() or None) if text is not None else None


def _week_bounds(day: date, today: date) -> tuple[date, date, bool]:
    """Start, end and "is the current week" of the church week containing `day`; a later week than
    the current one raises `FutureWeekError`."""
    week_start = church_sunday(day)
    current_week_start = church_sunday(today)
    if week_start > current_week_start:
        raise FutureWeekError
    return week_start, week_start + timedelta(days=6), week_start == current_week_start


def _open_report_groups(session: Session, only_group_ids: frozenset[int] | None) -> list[ReportGroupRow]:
    """Groups open today, all or only `only_group_ids`, by name."""
    if only_group_ids is not None and not only_group_ids:
        return []
    return [
        g for g in all_as(session, report_groups_query(only_group_ids), ReportGroupRow) if g.closed_at is None
    ]


def _active_leaders_by_group(session: Session, group_ids: frozenset[int]) -> dict[int, list[WeekLeader]]:
    """Each group's leaders today: the leader first, then co-leaders by name."""
    leaders: dict[int, list[WeekLeader]] = {}
    for row in all_as(session, active_leaders_query(group_ids), ActiveLeaderRow):
        leaders.setdefault(row.small_group_id, []).append(
            WeekLeader(row.member_id, row.member_name, row.role)
        )
    return leaders


def _week_groups(
    session: Session,
    groups: Sequence[ReportGroupRow],
    week_start: date,
    today: date,
    leaders: dict[int, list[WeekLeader]],
) -> list[WeekGroup]:
    """Each group's week status (dashboard rule 6), in the order of `groups`."""
    ids = frozenset(g.id for g in groups)
    reports: dict[int, list[WeekReportRow]] = {}
    for report in all_as(
        session, week_reports_query(ids, week_start, week_start + timedelta(days=6)), WeekReportRow
    ):
        reports.setdefault(report.small_group_id, []).append(report)
    leadership = _leadership_by_group(session, ids)
    return [
        _week_group(
            g, week_start, today, reports.get(g.id, []), leaders.get(g.id, []), leadership.get(g.id, [])
        )
        for g in groups
    ]


def _week_group(
    group: ReportGroupRow,
    week_start: date,
    today: date,
    reports: list[WeekReportRow],
    leaders: list[WeekLeader],
    leadership: list[LeadershipPeriod],
) -> WeekGroup:
    # The week starts on Sunday and `meeting_day` is ISO (Mon 1 .. Sun 7): Sunday (7) is day 0.
    meeting_date = (
        week_start + timedelta(days=group.meeting_day % 7) if group.meeting_day is not None else None
    )
    status: WeekStatus
    if any(r.held for r in reports):
        status = "submitted"
    elif reports:
        status = "notHeld"
    elif meeting_date is None:
        status = "noMeetingDay"
    else:
        # Same per-date test as rule 10, but a meeting still ahead is judged by who leads today.
        check = min(meeting_date, today)
        if not any(p.joined_at <= check and (p.left_at is None or p.left_at >= check) for p in leadership):
            status = "noLeader"
        elif meeting_date < today:
            status = "notFiled"
        elif meeting_date == today:
            status = "today"
        else:
            status = "upcoming"
    # Meetings first, then no meetings; stable, so each keeps its newest-first order.
    reports = sorted(reports, key=lambda r: not r.held)
    return WeekGroup(group=group, leaders=leaders, status=status, meeting_date=meeting_date, reports=reports)


def _validate_date(
    session: Session,
    small_group: SmallGroup,
    meeting_date: date,
    *,
    today: date,
    ignore_report_id: int | None,
    replaces_no_meeting: bool,
) -> SmallGroupReport | None:
    """Rules 1, 2 and 8 for a create or edit (closed, future, duplicate, in that order).

    Returns the no meeting the new report replaces (rule 13.5), or None. A held report is never replaced.
    """
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    if meeting_date > today:
        raise FutureMeetingDateError
    existing = session.execute(report_on_date_query(small_group.id, meeting_date)).one_or_none()
    if existing is None or existing.id == ignore_report_id:
        return None
    if replaces_no_meeting and not existing.held:
        return session.get(SmallGroupReport, existing.id)
    raise ReportAlreadyExistsError(existing.id, existing.held)


def _validated_roster(session: Session, small_group: SmallGroup, body: ReportInput) -> list[RosterPerson]:
    """Rule 3 for a held report; a no meeting has no attendance. Returns the roster on the meeting date."""
    roster = roster_on_date(session, small_group.id, body.meeting_date)
    if not body.held:
        return roster
    sent_ids = [a.member_id for a in body.attendances]
    # Exactly one row per person on the roster: no missing, extra or repeated members.
    if len(sent_ids) != len(set(sent_ids)) or set(sent_ids) != {p.member_id for p in roster}:
        raise AttendanceMismatchError
    return roster


def _commit_report_or_raise_conflict(session: Session, small_group_id: int, meeting_date: date) -> None:
    """Commit, mapping a lost race on (group, meeting date) to the same error as the check."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if "uq_small_group_reports_small_group_id" in str(exc.orig):
            existing = session.execute(report_on_date_query(small_group_id, meeting_date)).one_or_none()
            if existing is not None:
                raise ReportAlreadyExistsError(existing.id, existing.held) from exc
        raise


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
    session: Session,
    small_group: SmallGroup,
    *,
    member_id: int,
    role: SmallGroupRole,
    today: date,
    joined_at: date | None = None,
) -> None:
    """Add the member from `joined_at` (default today); a past date backfills migrated data."""
    joined_at = joined_at or today
    if joined_at > today:
        raise JoinedInFutureError
    if small_group.closed_at is not None:
        raise SmallGroupClosedError
    if session.get(Member, member_id) is None:
        raise MemberNotFoundError
    if get_active_membership(session, small_group.id, member_id) is not None:
        raise MemberAlreadyInGroupError
    if _overlaps_past_period(session, small_group.id, member_id, joined_at):
        raise MembershipOverlapError
    _ensure_leader_slot_free(session, small_group.id, role)
    _add_membership(session, small_group.id, member_id, role, joined_at)
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


def _overlaps_past_period(session: Session, small_group_id: int, member_id: int, joined_at: date) -> bool:
    """True if the member's closed history in the group extends past `joined_at`."""
    return (
        session.scalars(
            select(SmallGroupMember.id).where(
                SmallGroupMember.small_group_id == small_group_id,
                SmallGroupMember.member_id == member_id,
                SmallGroupMember.left_at > joined_at,
            )
        ).first()
        is not None
    )


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
