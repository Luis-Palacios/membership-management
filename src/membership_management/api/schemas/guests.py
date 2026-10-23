from datetime import date, datetime

from pydantic import EmailStr

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.members import Address, Name, Phone
from membership_management.data.members.models import MemberSex
from membership_management.data.small_groups.models import LeftReason, SmallGroupRole


class NewGuestSchema(CamelModel):
    """The fields for a new guest; everything but the name is optional (rule 3)."""

    name: Name
    phone: Phone | None = None
    email: EmailStr | None = None
    sex: MemberSex | None = None
    address: Address | None = None
    # Defaults to the day they join a group, or today.
    first_visit_date: date | None = None
    invited_by_member_id: int | None = None


class GuestCurrentGroupSchema(CamelModel):
    id: int
    name: str
    joined_at: date


class GuestLastGroupSchema(CamelModel):
    id: int
    name: str
    left_at: date
    left_reason: LeftReason | None


class GuestListItemSchema(CamelModel):
    id: int
    name: str
    phone: str | None
    first_visit_date: date | None
    # Exactly one of these is set for a guest who has been in a group; neither for one who never was.
    current_group: GuestCurrentGroupSchema | None
    last_group: GuestLastGroupSchema | None
    last_attended_date: date | None
    # In the current group as of today; null when in no group.
    missed_streak: int | None


class GuestListCountsSchema(CamelModel):
    all: int
    active: int
    inactive: int


class GuestListSchema(CamelModel):
    items: list[GuestListItemSchema]
    counts: GuestListCountsSchema
    total: int
    page: int
    page_size: int


class GuestSearchLastGroupSchema(CamelModel):
    id: int
    name: str
    left_at: date


class GuestSearchItemSchema(CamelModel):
    """Rule 14, and nothing more: enough to recognise someone, no email, address or observations."""

    id: int
    name: str
    phone_last4: str | None
    current_group: GuestCurrentGroupSchema | None
    last_group: GuestSearchLastGroupSchema | None
    last_attended_date: date | None


class GuestRefSchema(CamelModel):
    id: int
    name: str


class GuestPeriodSchema(CamelModel):
    small_group_id: int
    small_group_name: str
    role: SmallGroupRole
    joined_at: date
    left_at: date | None
    left_reason: LeftReason | None


class GuestAttendanceSchema(CamelModel):
    report_id: int
    meeting_date: date
    small_group: GuestRefSchema
    attended_group: bool
    attended_church: bool
    # Null unless the viewer may read this row's observations (reports rule 9).
    observation: str | None


class GuestDetailSchema(CamelModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    sex: MemberSex | None
    address: str | None
    first_visit_date: date | None
    invited_by: GuestRefSchema | None
    created_by: GuestRefSchema | None
    created_at: datetime
    current_group: GuestCurrentGroupSchema | None
    last_attended_date: date | None
    # Every period in a guest group, newest first.
    group_history: list[GuestPeriodSchema]
    # The last 12 attendance rows; a leader only gets the rows of the groups they lead.
    recent_attendance: list[GuestAttendanceSchema]


class GuestCreateSchema(NewGuestSchema):
    """A new guest in no group, or straight into a guest group (`smallGroupId`, joining today)."""

    small_group_id: int | None = None


class GuestUpdateSchema(CamelModel):
    """Partial update: contact, first visit, invited by; never groups. Null clears an optional field."""

    name: Name | None = None
    phone: Phone | None = None
    email: EmailStr | None = None
    sex: MemberSex | None = None
    address: Address | None = None
    first_visit_date: date | None = None
    invited_by_member_id: int | None = None
