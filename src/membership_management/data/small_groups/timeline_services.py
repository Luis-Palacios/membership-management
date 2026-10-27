import calendar
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy.orm import Session

from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.models import ReportSection, SmallGroupRole
from membership_management.data.small_groups.queries import people_query
from membership_management.data.small_groups.report_items import Segment, tagged_people, text_to_segments
from membership_management.data.small_groups.results import (
    PersonKey,
    PersonTimeline,
    ReportItemRow,
    ReportItemView,
    TaggedPersonRow,
    TimelineAttendance,
    TimelineCounts,
    TimelineGroup,
    TimelineObservation,
    TimelinePeriod,
    TimelineReportRow,
    TimelineRow,
)
from membership_management.data.small_groups.timeline_queries import (
    person_timeline_items_query,
    person_timeline_periods_query,
    person_timeline_reports_query,
)

# Report tags, person timeline: the default window and the longest one.
DEFAULT_RANGE_MONTHS = 3
MAX_RANGE_DAYS = 731


class TimelineRangeError(Exception):
    """The requested dates are not a valid range; the message is the 422 `detail`."""


def _months_back(d: date, months: int) -> date:
    """`d` minus whole months, clamped to the end of a shorter month (31 May - 3 = 28/29 Feb)."""
    index = d.year * 12 + (d.month - 1) - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(d.day, calendar.monthrange(year, month + 1)[1]))


def resolve_range(from_: date | None, to: date | None, *, today: date) -> tuple[date, date]:
    """`to` defaults to today, `from` to three months before `to` plus a day; validates both."""
    end = to if to is not None else today
    if end > today:
        raise TimelineRangeError("The range can't end in the future.")
    start = from_ if from_ is not None else _months_back(end, DEFAULT_RANGE_MONTHS) + timedelta(days=1)
    if start > end:
        raise TimelineRangeError("The range must start on or before its end.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise TimelineRangeError("The range can't be longer than 2 years.")
    return start, end


def _role_on(periods: Iterable[TimelinePeriod], small_group_id: int, d: date) -> SmallGroupRole | None:
    """The role of the period covering `d`; on a role change day, the one still running after it."""
    covering = [
        p
        for p in periods
        if p.small_group_id == small_group_id and p.joined_at <= d and (p.left_at is None or p.left_at >= d)
    ]
    if not covering:
        return None
    best = max(covering, key=lambda p: (p.left_at is None or p.left_at > d, p.joined_at, p.period_id))
    return best.role


def _visible_row(
    report: TimelineReportRow,
    items: list[ReportItemRow],
    periods: list[TimelinePeriod],
    *,
    in_audience: bool,
) -> (
    tuple[TimelineReportRow, list[ReportItemRow], TimelineAttendance | None, TimelineObservation | None]
    | None
):
    """Rule 23 for one report: attendance, observation and follow-up items need the observation audience."""
    shown = [i for i in items if in_audience or i.section != ReportSection.FOLLOW_UP]
    attendance = None
    observation = None
    if in_audience and report.attended_group is not None and report.attended_church is not None:
        attendance = TimelineAttendance(
            _role_on(periods, report.small_group_id, report.meeting_date),
            report.attended_group,
            report.attended_church,
        )
        text = (report.observation or "").strip()
        if text:
            observation = TimelineObservation(text, report.submitted_by_member_id, report.submitted_by_name)
    if attendance is None and not shown:
        return None
    return report, shown, attendance, observation


def get_person_timeline(
    session: Session,
    person: PersonKey,
    *,
    observation_groups: frozenset[int] | None,
    from_: date | None,
    to: date | None,
    small_group_id: int | None,
    latest: int | None,
) -> PersonTimeline:
    """A member's or guest's timeline as the caller may see it (report tags rules 21 to 23).

    `observation_groups` is the caller's observation audience: every group (None) or just these.
    Attendance, observations and follow-up items of other groups' reports are left out; prayer and
    praise items tagging the person are shown for any group. With `latest`, the newest N visible rows
    of any date and group; otherwise `from_` and `to` (already resolved) and optionally one group.
    Everything is loaded for all dates, since `groups` and `earliest_date` look past the range; a
    person's reports are few.
    """
    reports = all_as(session, person_timeline_reports_query(person), TimelineReportRow)
    periods = list(all_as(session, person_timeline_periods_query(person), TimelinePeriod))
    items_by_report: dict[int, list[ReportItemRow]] = defaultdict(list)
    for item in all_as(session, person_timeline_items_query(person), ReportItemRow):
        items_by_report[item.report_id].append(item)

    visible = []
    for report in reports:
        in_audience = observation_groups is None or report.small_group_id in observation_groups
        row = _visible_row(
            report, items_by_report.get(report.report_id, []), periods, in_audience=in_audience
        )
        if row is not None:
            visible.append(row)
    visible.sort(key=lambda r: (r[0].meeting_date, r[0].report_id), reverse=True)

    groups = {
        r[0].small_group_id: TimelineGroup(
            r[0].small_group_id, r[0].small_group_name, r[0].small_group_audience
        )
        for r in visible
    }
    earliest = min((r[0].meeting_date for r in visible), default=None)

    if latest is not None:
        chosen = visible[:latest]
        start = end = None
    else:
        if from_ is None or to is None:
            raise ValueError("a timeline needs `latest` or both dates; use resolve_range")
        start, end = from_, to
        chosen = [
            r
            for r in visible
            if from_ <= r[0].meeting_date <= to
            and (small_group_id is None or r[0].small_group_id == small_group_id)
        ]

    shown_items = [i for _, items, _, _ in chosen for i in items]
    names = _names(session, shown_items)
    rows = [
        TimelineRow(
            report.report_id,
            report.meeting_date,
            groups[report.small_group_id],
            attendance,
            observation,
            [_item_view(i, names) for i in items],
        )
        for report, items, attendance, observation in chosen
    ]
    counts = TimelineCounts(
        notes=sum(1 for row in rows if row.observation is not None),
        prayer=sum(1 for i in shown_items if i.section == ReportSection.PRAYER),
        praise=sum(1 for i in shown_items if i.section == ReportSection.PRAISE),
        follow_up=sum(1 for i in shown_items if i.section == ReportSection.FOLLOW_UP),
    )
    return PersonTimeline(
        start,
        end,
        earliest,
        sorted(groups.values(), key=lambda g: (g.name, g.id)),
        counts,
        rows,
    )


def _names(session: Session, items: Iterable[ReportItemRow]) -> dict[PersonKey, str]:
    """Current names of everyone the items tag (the person included): one query for the response."""
    tagged = {person for item in items for person in tagged_people(item.text)}
    member_ids = frozenset(i for kind, i in tagged if kind == "member")
    guest_ids = frozenset(i for kind, i in tagged if kind == "guest")
    if not tagged:
        return {}
    rows = all_as(session, people_query(member_ids, guest_ids), TaggedPersonRow)
    return {(row.kind, row.id): row.name for row in rows}


def _item_view(item: ReportItemRow, names: dict[PersonKey, str]) -> ReportItemView:
    segments: list[Segment] = text_to_segments(item.text, names)
    return ReportItemView(item.id, ReportSection(item.section), segments)
