import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple

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
    TimelineEntry,
    TimelineGroup,
    TimelineGroupRow,
    TimelineObservation,
    TimelinePeriod,
    TimelineReportEntry,
    TimelineReportRow,
    TimelineRow,
    TimelineStatusEntry,
    TimelineStatusRow,
)
from membership_management.data.small_groups.timeline_queries import (
    person_timeline_earliest_status_change_query,
    person_timeline_groups_query,
    person_timeline_items_query,
    person_timeline_periods_query,
    person_timeline_reports_query,
    person_timeline_status_changes_query,
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


def _visible_parts(
    report: TimelineReportRow,
    items: list[ReportItemRow],
    periods: list[TimelinePeriod],
    *,
    in_audience: bool,
) -> tuple[list[ReportItemRow], TimelineAttendance | None, TimelineObservation | None]:
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
    return shown, attendance, observation


@dataclass(frozen=True)
class _TimelineRequest:
    """What every source is given: the person, the caller's access, and `latest` or the range."""

    person: PersonKey
    # The caller's observation audience: every group (None) or just these.
    observation_groups: frozenset[int] | None
    from_: date | None
    to: date | None
    small_group_id: int | None
    latest: int | None


class _SourceResult(NamedTuple):
    # Already filtered for the caller and by the request, newest first, at most `latest`.
    entries: list[TimelineEntry]
    # The source's oldest entry and its groups, for this caller but whatever the range and group.
    earliest_date: date | None
    groups: list[TimelineGroup]


def _report_source(session: Session, request: _TimelineRequest) -> _SourceResult:
    """The held reports the person has an attendance line in or is tagged in (report tags rules 21 to 23)."""
    person, observation_groups = request.person, request.observation_groups
    group_rows = all_as(session, person_timeline_groups_query(person, observation_groups), TimelineGroupRow)
    reports = all_as(
        session,
        person_timeline_reports_query(
            person,
            observation_groups,
            from_=request.from_,
            to=request.to,
            small_group_id=request.small_group_id,
            latest=request.latest,
        ),
        TimelineReportRow,
    )
    periods = list(all_as(session, person_timeline_periods_query(person), TimelinePeriod))
    items_by_report: dict[int, list[ReportItemRow]] = defaultdict(list)
    report_ids = [report.report_id for report in reports]
    for item in all_as(session, person_timeline_items_query(person, report_ids), ReportItemRow):
        items_by_report[item.report_id].append(item)

    visible = [
        (
            report,
            *_visible_parts(
                report,
                items_by_report[report.report_id],
                periods,
                in_audience=observation_groups is None or report.small_group_id in observation_groups,
            ),
        )
        for report in reports
    ]
    names = _names(session, [item for _, items, _, _ in visible for item in items])
    entries: list[TimelineEntry] = [
        TimelineReportEntry(
            report.meeting_date,
            TimelineRow(
                report.report_id,
                report.meeting_date,
                TimelineGroup(report.small_group_id, report.small_group_name, report.small_group_audience),
                attendance,
                observation,
                [_item_view(i, names) for i in items],
            ),
        )
        for report, items, attendance, observation in visible
    ]
    return _SourceResult(
        entries,
        min((g.earliest_date for g in group_rows), default=None),
        [TimelineGroup(g.id, g.name, g.audience) for g in group_rows],
    )


def _status_source(session: Session, request: _TimelineRequest) -> _SourceResult:
    """The person's status changes, on their effective date. Whoever can open the timeline sees them,
    reason and note included (inactive-guests rule 13). They have no group, so picking one hides them."""
    entries: list[TimelineEntry] = []
    if request.small_group_id is None:
        changes = all_as(
            session,
            person_timeline_status_changes_query(
                request.person, from_=request.from_, to=request.to, latest=request.latest
            ),
            TimelineStatusRow,
        )
        entries = [TimelineStatusEntry(change.effective_date, change) for change in changes]
    earliest = session.scalar(person_timeline_earliest_status_change_query(request.person))
    return _SourceResult(entries, earliest, [])


# A new kind of entry is one more source here and in `TimelineEntry`. No source knows about the others.
# The order breaks ties on a date: an earlier source's entries go above a later one's (rule 15).
_SOURCES = (_status_source, _report_source)


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
    """A member's or guest's timeline as the caller may see it, merged from every source.

    `observation_groups` is the caller's observation audience: every group (None) or just these. With
    `latest`, the newest N visible entries of any date, kind and group; otherwise `from_` and `to`
    (already resolved) and optionally one group.
    """
    if latest is None and (from_ is None or to is None):
        raise ValueError("a timeline needs `latest` or both dates; use resolve_range")
    request = _TimelineRequest(person, observation_groups, from_, to, small_group_id, latest)
    results = [source(session, request) for source in _SOURCES]

    all_entries = [entry for result in results for entry in result.entries]
    # A stable sort, so within a date the entries stay in source order, each source's newest first.
    entries = sorted(all_entries, key=lambda entry: entry.entry_date, reverse=True)
    if latest is not None:
        entries = entries[:latest]
    # `rows` stays what it was before entries existed (a report isn't cut for a newer status entry) until
    # staff-app reads `entries` and it goes: the expand of rule 15.
    rows = [entry.row for entry in all_entries if isinstance(entry, TimelineReportEntry)]
    shown_items = [item for row in rows for item in row.items]
    counts = TimelineCounts(
        notes=sum(1 for row in rows if row.observation is not None),
        prayer=sum(1 for i in shown_items if i.section == ReportSection.PRAYER),
        praise=sum(1 for i in shown_items if i.section == ReportSection.PRAISE),
        follow_up=sum(1 for i in shown_items if i.section == ReportSection.FOLLOW_UP),
    )
    return PersonTimeline(
        from_,
        to,
        min((r.earliest_date for r in results if r.earliest_date is not None), default=None),
        sorted((g for r in results for g in r.groups), key=lambda g: (g.name, g.id)),
        counts,
        rows,
        entries,
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
