from datetime import date
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
