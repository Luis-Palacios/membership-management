from datetime import date, datetime
from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, EmailStr, StringConstraints, field_validator

from membership_management.api.schemas.base import CamelModel
from membership_management.data.members.models import MemberInactiveReason, MemberSex, MemberStatus
from membership_management.data.small_groups.models import SmallGroupRole

# Strip whitespace; limits match the member columns.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class MemberOptionSchema(CamelModel):
    id: int
    name: str


class MemberSearchResultSchema(CamelModel):
    id: int
    name: str
    status: MemberStatus


class MemberSummarySchema(CamelModel):
    id: int
    name: str
    email: str | None
    phone: str | None
    user_id: str | None
    status: MemberStatus
    inactive_since: date | None
    # Private (rule 5): null unless the caller has `members: setStatus`.
    inactive_reason: MemberInactiveReason | None


class MemberSmallGroupSchema(CamelModel):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date


class MemberPastSmallGroupSchema(CamelModel):
    """A period the member's latest deactivation ended."""

    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date


class MemberDetailSchema(CamelModel):
    id: int
    name: str
    email: str | None
    phone: str | None
    address: str | None
    birth_date: date | None
    sex: MemberSex | None
    user_id: str | None
    small_groups: list[MemberSmallGroupSchema]
    status: MemberStatus
    # The date they left, from the latest deactivation; null while active.
    inactive_since: date | None
    # Private (inactive-members rule 5): null unless the caller has `members: setStatus`.
    inactive_reason: MemberInactiveReason | None
    inactive_note: str | None
    past_small_groups: list[MemberPastSmallGroupSchema]


def _blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


# Trimmed, an empty note becomes null, at most 1000 characters.
Note = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
    BeforeValidator(_blank_to_none),
]


class MemberDeactivateSchema(CamelModel):
    reason: MemberInactiveReason
    # The date they left: today or earlier.
    effective_date: date
    note: Note = None


class MemberReactivateSchema(CamelModel):
    note: Note = None


class MemberStatusChangeSchema(CamelModel):
    status: MemberStatus
    reason: MemberInactiveReason | None
    effective_date: date
    note: str | None
    changed_by_user_id: str
    changed_by_name: str | None
    created_at: datetime


class MemberCreateSchema(CamelModel):
    name: Name
    email: EmailStr | None = None
    phone: Phone | None = None
    address: Address | None = None
    birth_date: date | None = None
    sex: MemberSex | None = None


class MemberUpdateSchema(CamelModel):
    """Partial update: only fields present in the body change; send null to clear an optional one."""

    name: Name | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    address: Address | None = None
    birth_date: date | None = None
    sex: MemberSex | None = None


class MemberUserLinkSchema(CamelModel):
    user_id: UserId


class MyMemberUpdateSchema(CamelModel):
    """Partial update of the caller's own member: the five fields they may edit, no email (rule 4).

    Unknown fields are a 422. Send null to clear an optional field; name cannot be null.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    phone: Phone | None = None
    address: Address | None = None
    birth_date: date | None = None
    sex: MemberSex | None = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value: str | None) -> str:
        # Only runs when name is sent (defaults aren't validated); the column is NOT NULL.
        if value is None:
            raise ValueError("name cannot be null.")
        return value
