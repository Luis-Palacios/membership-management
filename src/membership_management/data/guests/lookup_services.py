from collections.abc import Sequence
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from membership_management.data.guests.models import Guest
from membership_management.data.guests.queries import (
    guest_active_in_groups_query,
    guest_counts_query,
    guest_periods_query,
    guest_recent_attendance_query,
    guest_rows_query,
    guests_active_in_groups_query,
    led_open_guest_group_ids_query,
)
from membership_management.data.guests.results import (
    GuestAttendanceRow,
    GuestCounts,
    GuestDetail,
    GuestPage,
    GuestPeriodRow,
    GuestRow,
)
from membership_management.data.query_helpers import all_as
from membership_management.data.small_groups.services import missed_streaks_by_person

GuestStatus = Literal["all", "active", "inactive"]
# How many attendance rows the guest detail shows: the missed-streak window (reports rule 11).
RECENT_ATTENDANCE_LIMIT = 12
SEARCH_LIMIT = 10


def get_led_open_guest_group_ids(session: Session, member_id: int) -> frozenset[int]:
    """Open guest groups the member leads or co-leads today: the guests scope of a caller without `all`."""
    return frozenset(session.scalars(led_open_guest_group_ids_query(member_id)))


def is_guest_in_groups(session: Session, guest_id: int, group_ids: frozenset[int]) -> bool:
    """Whether the guest has an open period in one of `group_ids` (empty: never, without a query)."""
    if not group_ids:
        return False
    return session.scalar(guest_active_in_groups_query(guest_id, group_ids)) is not None


def guests_in_groups(
    session: Session, guest_ids: frozenset[int], group_ids: frozenset[int]
) -> frozenset[int]:
    """`is_guest_in_groups` for many guests in one query: the ids it holds for."""
    if not guest_ids or not group_ids:
        return frozenset()
    return frozenset(session.scalars(guests_active_in_groups_query(guest_ids, group_ids)))


def get_guest(session: Session, guest_id: int) -> Guest | None:
    return session.get(Guest, guest_id)


def list_guests(
    session: Session, *, status: GuestStatus, q: str | None, page: int, page_size: int, today: date
) -> GuestPage:
    """One page of guests by name, filtered by status and search text, with the tab counts.

    Counts follow the search but not the status filter, so every tab shows its own number.
    """
    counts_row = session.execute(guest_counts_query(q)).one()
    counts = GuestCounts(
        all=counts_row.all, active=counts_row.active, inactive=counts_row.all - counts_row.active
    )
    only_active = {"all": None, "active": True, "inactive": False}[status]
    rows = list(
        all_as(
            session,
            guest_rows_query(
                match_text=q, only_active=only_active, limit=page_size, offset=(page - 1) * page_size
            ),
            GuestRow,
        )
    )
    return GuestPage(rows, _current_group_streaks(session, rows, today), counts, getattr(counts, status))


def _current_group_streaks(session: Session, rows: Sequence[GuestRow], today: date) -> dict[int, int]:
    """Each in-a-group guest's missed streak in their current group as of `today` (one query per group)."""
    by_group: dict[int, list[int]] = {}
    for row in rows:
        if row.current_group_id is not None:
            by_group.setdefault(row.current_group_id, []).append(row.id)
    streaks: dict[int, int] = {}
    for group_id, guest_ids in by_group.items():
        by_person = missed_streaks_by_person(session, group_id, [("guest", i) for i in guest_ids], today)
        streaks.update({guest_id: by_person[("guest", guest_id)] for guest_id in guest_ids})
    return streaks


def search_guests(session: Session, text: str) -> Sequence[GuestRow]:
    """At most SEARCH_LIMIT guests matching `text` church-wide, best matches first.

    No scope here: the caller decides who may search (rule 17); the route only returns rule 14's fields.
    """
    return all_as(
        session, guest_rows_query(match_text=text, best_matches_first=True, limit=SEARCH_LIMIT), GuestRow
    )


def get_guest_detail(
    session: Session,
    guest: Guest,
    *,
    only_group_ids: frozenset[int] | None,
    sees_all_observations: bool,
    led_group_ids: frozenset[int],
) -> GuestDetail:
    """The guest as the viewer may see it (rule 15).

    `only_group_ids` limits the attendance rows to those groups (a scoped caller gets the groups they
    lead; None: every row). An attendance row's observation is readable with `sees_all_observations`
    or when its group is among `led_group_ids` (reports rule 9).
    """
    row = all_as(session, guest_rows_query(only_ids=[guest.id]), GuestRow)[0]
    attendance = list(
        all_as(
            session,
            guest_recent_attendance_query(guest.id, only_group_ids, RECENT_ATTENDANCE_LIMIT),
            GuestAttendanceRow,
        )
    )
    return GuestDetail(
        row=row,
        phone=guest.phone,
        email=guest.email,
        sex=guest.sex,
        address=guest.address,
        invited_by=(guest.invited_by.id, guest.invited_by.name) if guest.invited_by is not None else None,
        created_by=(guest.created_by.id, guest.created_by.name) if guest.created_by is not None else None,
        created_at=guest.created_at,
        periods=list(all_as(session, guest_periods_query(guest.id), GuestPeriodRow)),
        attendance=attendance,
        observations_visible_in=frozenset(
            a.report_id for a in attendance if sees_all_observations or a.small_group_id in led_group_ids
        ),
    )
