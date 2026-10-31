from datetime import date, datetime
from typing import NamedTuple

from membership_management.data.guests.models import GuestInactiveReason, GuestStatus
from membership_management.data.small_groups.models import LeftReason, SmallGroupRole


class GuestRow(NamedTuple):
    """A guest with their status, where they are now (or were last) and when they last attended; the list
    and search row. Status is separate from being in a group: an active guest may be in none.

    The reason is private (rule 9): callers without `guests: deactivate` must not pass it on.
    """

    id: int
    name: str
    phone: str | None
    first_visit_date: date | None
    status: GuestStatus
    # From the latest change, while inactive; None otherwise.
    inactive_since: date | None
    inactive_reason: GuestInactiveReason | None
    current_group_id: int | None
    current_group_name: str | None
    current_joined_at: date | None
    last_group_id: int | None
    last_group_name: str | None
    last_left_at: date | None
    last_left_reason: LeftReason | None
    last_attended_date: date | None


class GuestCounts(NamedTuple):
    """Guests matching the search, by status."""

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


class GuestStatusChangeRow(NamedTuple):
    status: GuestStatus
    reason: GuestInactiveReason | None
    effective_date: date
    note: str | None
    changed_by_user_id: str
    # The name of the member linked to `changed_by_user_id`, if there is one.
    changed_by_name: str | None
    created_at: datetime


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
    # Newest first; None unless the viewer may read reasons and notes (rule 9).
    status_history: list[GuestStatusChangeRow] | None
