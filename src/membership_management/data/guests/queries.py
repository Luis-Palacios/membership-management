import re

from sqlalchemy import ColumnElement, ScalarSelect, Select, case, func, literal_column, or_, select
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql import Subquery

from membership_management.data.guests.models import Guest, GuestStatus, GuestStatusChange
from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
    GroupAudience,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)

# Digits of a phone number, for matching "last 4 digits" and formats like "+505 8367 0887".
_NON_DIGITS = re.compile(r"\D")
# Digits needed in the query before it also matches phone numbers (below that, "50" would match everyone).
PHONE_SEARCH_MIN_DIGITS = 3


def search_text(value: str) -> ColumnElement[str]:
    """lower(unaccent(value)) through the migration's IMMUTABLE wrapper, the expression the GIN index has."""
    return func.guest_search_text(value)


def phone_digits_column() -> ColumnElement[str]:
    # Literals, not bound parameters, so the planner can match the expression to `ix_guests_phone_digits`.
    return func.regexp_replace(
        Guest.phone, literal_column(r"'\D'"), literal_column("''"), literal_column("'g'")
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def guest_name_match(text: str, *, prefix: bool = False) -> ColumnElement[bool]:
    """Guests whose name contains `text` (starts with it, with `prefix`), ignoring case and accents."""
    pattern = f"{_escape_like(text)}%" if prefix else f"%{_escape_like(text)}%"
    return func.guest_search_text(Guest.name).like(search_text(pattern), escape="\\")


def guest_match_condition(text: str) -> ColumnElement[bool]:
    """Guests whose name contains `text` (ignoring case and accents), or whose phone contains its digits
    when it has at least PHONE_SEARCH_MIN_DIGITS."""
    by_name = guest_name_match(text)
    digits = _NON_DIGITS.sub("", text)
    if len(digits) < PHONE_SEARCH_MIN_DIGITS:
        return by_name
    return or_(by_name, phone_digits_column().like(f"%{digits}%"))


def _current_period() -> Subquery:
    """Each guest's open period (the partial unique index allows at most one) with its group's name."""
    return (
        select(
            SmallGroupMember.guest_id.label("guest_id"),
            SmallGroup.id.label("group_id"),
            SmallGroup.name.label("group_name"),
            SmallGroupMember.joined_at.label("joined_at"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.guest_id.is_not(None), SmallGroupMember.left_at.is_(None))
        .subquery("current_period")
    )


def _last_period() -> Subquery:
    """Each guest's newest ended period (latest end date, then latest row)."""
    return (
        select(
            SmallGroupMember.guest_id.label("guest_id"),
            SmallGroup.id.label("group_id"),
            SmallGroup.name.label("group_name"),
            SmallGroupMember.left_at.label("left_at"),
            SmallGroupMember.left_reason.label("left_reason"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.guest_id.is_not(None), SmallGroupMember.left_at.is_not(None))
        .distinct(SmallGroupMember.guest_id)
        .order_by(SmallGroupMember.guest_id, SmallGroupMember.left_at.desc(), SmallGroupMember.id.desc())
        .subquery("last_period")
    )


def _last_attended() -> Subquery:
    """The newest meeting date each guest attended, in any group."""
    return (
        select(
            SmallGroupReportAttendance.guest_id.label("guest_id"),
            func.max(SmallGroupReport.meeting_date).label("last_attended_date"),
        )
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportAttendance.report_id)
        .where(
            SmallGroupReportAttendance.guest_id.is_not(None),
            SmallGroupReportAttendance.attended_group.is_(True),
        )
        .group_by(SmallGroupReportAttendance.guest_id)
        .subquery("last_attended")
    )


def _latest_status_change_column(column: InstrumentedAttribute) -> ScalarSelect:
    """`column` of the guest's latest status change (correlated to `guests`)."""
    return (
        select(column)
        .where(GuestStatusChange.guest_id == Guest.id)
        .order_by(GuestStatusChange.created_at.desc(), GuestStatusChange.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def guest_rows_query(
    *,
    match_text: str | None = None,
    status: GuestStatus | None = None,
    only_ids: list[int] | None = None,
    best_matches_first: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> Select:
    """Guests with their status, current group, last group and last attended date (`GuestRow`).

    `match_text` keeps the guests matching that search, `status` those with that status (None: all).
    Inactive ones carry the date they left and why. Ordered by name, or with `best_matches_first` (needs
    `match_text`) exact name matches first, then names starting with it, then the rest, each by most
    recently seen.
    """
    current, last, attended = _current_period(), _last_period(), _last_attended()
    inactive = Guest.status == GuestStatus.INACTIVE
    query = (
        select(
            Guest.id.label("id"),
            Guest.name.label("name"),
            Guest.phone.label("phone"),
            Guest.first_visit_date.label("first_visit_date"),
            Guest.status.label("status"),
            case((inactive, _latest_status_change_column(GuestStatusChange.effective_date))).label(
                "inactive_since"
            ),
            case((inactive, _latest_status_change_column(GuestStatusChange.reason))).label("inactive_reason"),
            current.c.group_id.label("current_group_id"),
            current.c.group_name.label("current_group_name"),
            current.c.joined_at.label("current_joined_at"),
            last.c.group_id.label("last_group_id"),
            last.c.group_name.label("last_group_name"),
            last.c.left_at.label("last_left_at"),
            last.c.left_reason.label("last_left_reason"),
            attended.c.last_attended_date.label("last_attended_date"),
        )
        .outerjoin(current, current.c.guest_id == Guest.id)
        .outerjoin(last, last.c.guest_id == Guest.id)
        .outerjoin(attended, attended.c.guest_id == Guest.id)
    )
    if match_text is not None:
        query = query.where(guest_match_condition(match_text))
    if status is not None:
        query = query.where(Guest.status == status)
    if only_ids is not None:
        query = query.where(Guest.id.in_(only_ids))
    if best_matches_first and match_text is not None:
        name = func.guest_search_text(Guest.name)
        rank = case(
            (name == search_text(match_text), 0),
            (name.like(search_text(f"{_escape_like(match_text)}%"), escape="\\"), 1),
            else_=2,
        )
        query = query.order_by(rank, attended.c.last_attended_date.desc().nulls_last(), Guest.name, Guest.id)
    else:
        query = query.order_by(Guest.name, Guest.id)
    if limit is not None:
        query = query.limit(limit).offset(offset)
    return query


def guest_counts_query(match_text: str | None) -> Select:
    """Guests matching the search (all if none), and how many of them are active."""
    query = select(
        func.count(Guest.id).label("all"),
        func.count(Guest.id).filter(Guest.status == GuestStatus.ACTIVE).label("active"),
    )
    if match_text is not None:
        query = query.where(guest_match_condition(match_text))
    return query


def led_open_guest_group_ids_query(member_id: int) -> Select:
    """Open guest groups the member leads or co-leads today (the guests scope of a caller without `all`)."""
    return (
        select(SmallGroup.id)
        .join(SmallGroupMember, SmallGroupMember.small_group_id == SmallGroup.id)
        .where(
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.role.in_([SmallGroupRole.LEADER, SmallGroupRole.CO_LEADER]),
            SmallGroupMember.left_at.is_(None),
            SmallGroup.audience == GroupAudience.GUESTS,
            SmallGroup.closed_at.is_(None),
        )
        .distinct()
    )


def guest_active_in_groups_query(guest_id: int, group_ids: frozenset[int]) -> Select:
    """One row if the guest has an open period in one of `group_ids` (the guests scope check)."""
    return (
        select(SmallGroupMember.id)
        .where(
            SmallGroupMember.guest_id == guest_id,
            SmallGroupMember.left_at.is_(None),
            SmallGroupMember.small_group_id.in_(group_ids),
        )
        .limit(1)
    )


def guests_active_in_groups_query(guest_ids: frozenset[int], group_ids: frozenset[int]) -> Select:
    """`guest_active_in_groups_query` for many guests at once: the ids among `guest_ids` it holds for."""
    return (
        select(SmallGroupMember.guest_id)
        .distinct()
        .where(
            SmallGroupMember.guest_id.in_(guest_ids),
            SmallGroupMember.left_at.is_(None),
            SmallGroupMember.small_group_id.in_(group_ids),
        )
    )


def guest_periods_query(guest_id: int) -> Select:
    """Every period of the guest, newest first."""
    return (
        select(
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
            SmallGroupMember.left_at.label("left_at"),
            SmallGroupMember.left_reason.label("left_reason"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.guest_id == guest_id)
        .order_by(SmallGroupMember.joined_at.desc(), SmallGroupMember.id.desc())
    )


def guest_status_history_query(guest_id: int) -> Select:
    """Every status change of the guest, newest first, with the name of whoever made it (when that user
    is linked to a member)."""
    changed_by = aliased(Member)
    return (
        select(
            GuestStatusChange.status.label("status"),
            GuestStatusChange.reason.label("reason"),
            GuestStatusChange.effective_date.label("effective_date"),
            GuestStatusChange.note.label("note"),
            GuestStatusChange.changed_by_user_id.label("changed_by_user_id"),
            changed_by.name.label("changed_by_name"),
            GuestStatusChange.created_at.label("created_at"),
        )
        .outerjoin(changed_by, changed_by.user_id == GuestStatusChange.changed_by_user_id)
        .where(GuestStatusChange.guest_id == guest_id)
        .order_by(GuestStatusChange.created_at.desc(), GuestStatusChange.id.desc())
    )


def guest_recent_attendance_query(guest_id: int, only_group_ids: frozenset[int] | None, limit: int) -> Select:
    """The guest's newest attendance rows (held reports only have rows), optionally only of some groups."""
    query = (
        select(
            SmallGroupReport.id.label("report_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroupReportAttendance.attended_group.label("attended_group"),
            SmallGroupReportAttendance.attended_church.label("attended_church"),
            SmallGroupReportAttendance.observation.label("observation"),
        )
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportAttendance.report_id)
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .where(SmallGroupReportAttendance.guest_id == guest_id)
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroupReport.id.desc())
        .limit(limit)
    )
    if only_group_ids is not None:
        query = query.where(SmallGroup.id.in_(only_group_ids))
    return query
