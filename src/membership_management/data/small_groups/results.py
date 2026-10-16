from datetime import date, datetime
from typing import Literal, NamedTuple

from membership_management.data.small_groups.models import SmallGroupRole


class SmallGroupSummary(NamedTuple):
    id: int
    name: str
    meeting_address: str | None
    meeting_day: int | None
    closed_at: date | None
    active_member_count: int
    leader_member_id: int | None
    leader_name: str | None


class SmallGroupActiveMember(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date


class RosterPeriod(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date | None
    period_id: int


class AttendanceMark(NamedTuple):
    member_id: int
    attended_group: bool


class RosterPerson(NamedTuple):
    """Someone who belongs in a report for a date, with the role they held that day."""

    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date
    missed_streak: int


class ReportRoster(NamedTuple):
    people: list[RosterPerson]
    existing_report_id: int | None


class AttendanceInput(NamedTuple):
    member_id: int
    attended_group: bool
    attended_church: bool
    observation: str | None


class ReportInput(NamedTuple):
    """The body of a create or edit, already trimmed (blank text is None)."""

    meeting_date: date
    address: str | None
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    attendances: list[AttendanceInput]


class ReportAttendanceView(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    # Start of the membership period covering the meeting date; None if memberships were edited since.
    joined_at: date | None
    attended_group: bool
    attended_church: bool
    missed_streak: int
    # Always None when the viewer may not see observations (rule 9), so no mapping can leak one.
    observation: str | None


class ReportDetail(NamedTuple):
    id: int
    small_group_id: int
    small_group_name: str
    small_group_meeting_address: str | None
    small_group_closed_at: date | None
    meeting_date: date
    address: str | None
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    submitted_by_member_id: int
    submitted_by_name: str
    submitted_at: datetime
    observations_visible: bool
    attendances: list[ReportAttendanceView]


class ReportGroupRow(NamedTuple):
    id: int
    name: str
    meeting_day: int | None
    closed_at: date | None


class FiledReportRow(NamedTuple):
    id: int
    small_group_id: int
    small_group_name: str
    small_group_closed_at: date | None
    meeting_date: date
    submitted_by_member_id: int
    submitted_by_name: str
    submitted_at: datetime
    roster_count: int
    attended_group_count: int
    attended_church_count: int


class NotFiledMeeting(NamedTuple):
    small_group_id: int
    small_group_name: str
    small_group_closed_at: date | None
    meeting_date: date


class ReportDate(NamedTuple):
    report_id: int
    small_group_id: int
    meeting_date: date


class LeadershipPeriod(NamedTuple):
    small_group_id: int
    joined_at: date
    left_at: date | None


class RecentMeeting(NamedTuple):
    """A date rule 10 looks at, with the report filed on it (None when not filed)."""

    date: date
    report_id: int | None


class GroupRole(NamedTuple):
    small_group_id: int
    role: SmallGroupRole


class ReportCounts(NamedTuple):
    all: int
    filed: int
    not_filed: int


class ReportPage(NamedTuple):
    items: list[FiledReportRow | NotFiledMeeting]
    counts: ReportCounts
    total: int


class GroupReportSummary(NamedTuple):
    group: ReportGroupRow
    role: SmallGroupRole | None
    last_report: FiledReportRow | None
    not_filed_dates: list[date]
    # An active leader or co-leader today.
    has_leader: bool
    # Newest first; `not_filed_dates` is the entries without a report.
    recent_meetings: list[RecentMeeting]


WeekStatus = Literal["submitted", "notFiled", "today", "upcoming", "noLeader", "noMeetingDay"]


class WeekReportRow(NamedTuple):
    """A report dated in the week, with counts only: observation text never leaves the database."""

    id: int
    small_group_id: int
    meeting_date: date
    roster_count: int
    attended_group_count: int
    attended_church_count: int
    observation_count: int
    submitted_by_member_id: int
    submitted_by_name: str


class ActiveLeaderRow(NamedTuple):
    small_group_id: int
    member_id: int
    member_name: str
    role: SmallGroupRole


class WeekLeader(NamedTuple):
    member_id: int
    name: str
    role: SmallGroupRole


class WeekGroup(NamedTuple):
    group: ReportGroupRow
    leaders: list[WeekLeader]
    status: WeekStatus
    # The week's date on the group's meeting day (even when the report is on another day).
    meeting_date: date | None
    reports: list[WeekReportRow]


class ReportWeek(NamedTuple):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    groups: list[WeekGroup]
