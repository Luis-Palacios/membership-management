from datetime import date
from typing import Annotated

from pydantic import EmailStr, StringConstraints

from membership_management.api.schemas.base import CamelModel
from membership_management.data.members.models import MemberSex
from membership_management.data.small_groups.models import SmallGroupRole

# Strip whitespace; limits match the member columns.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class MemberOptionSchema(CamelModel):
    id: int
    name: str


class MemberSummarySchema(CamelModel):
    id: int
    name: str
    email: str | None
    phone: str | None
    user_id: str | None


class MemberSmallGroupSchema(CamelModel):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date


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
