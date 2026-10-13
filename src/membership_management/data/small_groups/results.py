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


class SmallGroupActiveMember(NamedTuple):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date
