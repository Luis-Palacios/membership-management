from datetime import date
from typing import Annotated

from pydantic import StringConstraints

from membership_management.api.schemas.base import CamelModel
from membership_management.data.small_groups.models import SmallGroupRole, Weekday

# Strip whitespace; limits match the small_groups columns.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
MeetingAddress = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class SmallGroupSummarySchema(CamelModel):
    id: int
    name: str
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None
    active_member_count: int
    leader_member_id: int | None
    leader_name: str | None


class SmallGroupMemberSchema(CamelModel):
    member_id: int
    member_name: str
    role: SmallGroupRole
    joined_at: date


class SmallGroupDetailSchema(CamelModel):
    id: int
    name: str
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None
    members: list[SmallGroupMemberSchema]


class SmallGroupCreateSchema(CamelModel):
    name: Name
    meeting_address: MeetingAddress | None = None
    meeting_day: Weekday | None = None


class SmallGroupUpdateSchema(CamelModel):
    """Partial update: only fields present in the body change; send null to clear an optional one."""

    name: Name | None = None
    meeting_address: MeetingAddress | None = None
    meeting_day: Weekday | None = None


class SmallGroupMemberAddSchema(CamelModel):
    member_id: int
    role: SmallGroupRole = SmallGroupRole.MEMBER


class SmallGroupMemberRoleSchema(CamelModel):
    role: SmallGroupRole


class SmallGroupLeaderSchema(CamelModel):
    member_id: int
