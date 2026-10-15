from datetime import date, datetime
from typing import NamedTuple

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
