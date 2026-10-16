from datetime import date
from typing import NamedTuple

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
