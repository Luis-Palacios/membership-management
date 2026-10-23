from datetime import date
from typing import Annotated, Literal, Self

from pydantic import StringConstraints, model_validator

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.guests import NewGuestSchema
from membership_management.api.schemas.person import PersonSchema
from membership_management.data.small_groups.models import GroupAudience, LeftReason, SmallGroupRole, Weekday

# Strip whitespace; limits match the small_groups columns.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
MeetingAddress = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class SmallGroupSummarySchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None
    # Members only; a guest group's guests are in `activeGuestCount` (0 for member groups).
    active_member_count: int
    active_guest_count: int
    leader_member_id: int | None
    leader_name: str | None


class SmallGroupMemberSchema(CamelModel):
    """One active participant: a member, or (in a guest group) a guest.

    `memberId`/`memberName` are null on guest rows until staff-app reads `person` everywhere.
    """

    person: PersonSchema
    member_id: int | None
    member_name: str | None
    role: SmallGroupRole
    joined_at: date
    # Guest rows of a guest group only (null otherwise): how many of the group's latest reports they
    # missed in a row as of today, and the last date they attended any meeting (null if never).
    missed_streak: int | None = None
    last_attended_date: date | None = None


class SmallGroupDetailSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None
    # Counts never mix the two (rule 20); `members` holds both kinds of participant.
    member_count: int
    guest_count: int
    members: list[SmallGroupMemberSchema]


class SmallGroupGuestAddedSchema(SmallGroupDetailSchema):
    """The group after adding a guest, plus that guest's id (a new guest's id isn't anywhere else)."""

    guest_id: int


class SmallGroupCreateSchema(CamelModel):
    name: Name
    meeting_address: MeetingAddress | None = None
    meeting_day: Weekday | None = None
    # Who the group is for; fixed once created. `guests` needs GUEST_GROUPS_ENABLED.
    audience: GroupAudience = GroupAudience.MEMBERS


class SmallGroupUpdateSchema(CamelModel):
    """Partial update: only fields present in the body change; send null to clear an optional one."""

    name: Name | None = None
    meeting_address: MeetingAddress | None = None
    meeting_day: Weekday | None = None
    # Accepted only to refuse it with a clear 422: a group's audience never changes (rule 5).
    audience: GroupAudience | None = None


class SmallGroupMemberAddSchema(CamelModel):
    member_id: int
    role: SmallGroupRole = SmallGroupRole.MEMBER
    # Defaults to today in the church's time zone; a past date backfills migrated data.
    joined_at: date | None = None


class SmallGroupMemberRoleSchema(CamelModel):
    role: SmallGroupRole


class SmallGroupLeaderSchema(CamelModel):
    member_id: int


class SmallGroupGuestAddSchema(CamelModel):
    """Add a guest to a guest group: an existing one (`guestId`) or a new one (`newGuest`), exactly one."""

    guest_id: int | None = None
    new_guest: NewGuestSchema | None = None
    # Defaults to today; the report form passes the meeting date.
    joined_at: date | None = None
    # Confirm moving a guest who is active in another guest group (rule 7).
    move_from_other_group: bool = False

    @model_validator(mode="after")
    def exactly_one_guest(self) -> Self:
        if (self.guest_id is None) == (self.new_guest is None):
            raise ValueError("Send either guestId or newGuest.")
        return self


class SmallGroupLeaveSchema(CamelModel):
    """Why and when someone left. `moved_group` is only ever set by a move, so it isn't accepted here."""

    left_reason: Literal[LeftReason.STOPPED_COMING, LeftReason.OTHER] | None = None
    # Defaults to today; never before they joined or before a report that already has their row.
    left_at: date | None = None
