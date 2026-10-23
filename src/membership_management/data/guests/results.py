from datetime import date, datetime
from typing import NamedTuple

from membership_management.data.small_groups.models import LeftReason, SmallGroupRole


class GuestRow(NamedTuple):
    """A guest with where they are now (or were last) and when they last attended; the list and search row."""

    id: int
    name: str
    phone: str | None
    first_visit_date: date | None
    current_group_id: int | None
    current_group_name: str | None
    current_joined_at: date | None
    last_group_id: int | None
    last_group_name: str | None
    last_left_at: date | None
    last_left_reason: LeftReason | None
    last_attended_date: date | None


class GuestCounts(NamedTuple):
    """Guests matching the search, by status: `active` are in a guest group today."""

    all: int
    active: int
    inactive: int


class GuestPage(NamedTuple):
    rows: list[GuestRow]
    # Missed streak in the current group, as of today; absent for guests in no group.
    missed_streaks: dict[int, int]
    counts: GuestCounts
    total: int


class GuestPeriodRow(NamedTuple):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date | None
    left_reason: LeftReason | None


class GuestAttendanceRow(NamedTuple):
    report_id: int
    meeting_date: date
    small_group_id: int
    small_group_name: str
    attended_group: bool
    attended_church: bool
    observation: str | None


class GuestDetail(NamedTuple):
    row: GuestRow
    phone: str | None
    email: str | None
    sex: str | None
    address: str | None
    invited_by: tuple[int, str] | None
    created_by: tuple[int, str] | None
    created_at: datetime
    periods: list[GuestPeriodRow]
    attendance: list[GuestAttendanceRow]
    # Attendance rows whose observation the viewer may read (rule 9), by report id.
    observations_visible_in: frozenset[int]
