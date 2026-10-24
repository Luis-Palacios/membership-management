from datetime import date, datetime
from typing import NamedTuple

from membership_management.data.members.models import MemberInactiveReason, MemberStatus
from membership_management.data.small_groups.models import SmallGroupRole


class MemberSummary(NamedTuple):
    id: int
    name: str
    email: str | None
    phone: str | None
    user_id: str | None


class MemberOption(NamedTuple):
    id: int
    name: str


class MemberSmallGroup(NamedTuple):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date


class MemberLead(NamedTuple):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole


class MemberLeadGroup(NamedTuple):
    """An open group the member is the leader of."""

    small_group_id: int
    small_group_name: str


class MemberPastSmallGroup(NamedTuple):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date


class MemberStatusChangeRow(NamedTuple):
    status: MemberStatus
    reason: MemberInactiveReason | None
    effective_date: date
    note: str | None
    changed_by_user_id: str
    # The name of the member linked to `changed_by_user_id`, if there is one.
    changed_by_name: str | None
    created_at: datetime
