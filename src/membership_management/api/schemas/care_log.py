from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import Field, PlainSerializer

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_group_reports import TagSearchGroupSchema
from membership_management.data.care.models import (
    CareLogKind,
    CareLogSourceKind,
    CareLogStatus,
    CareLogVisibility,
)
from membership_management.data.small_groups.models import ReportSection

# "12:30", not "12:30:00": the API sends and takes hours and minutes.
ClockTime = Annotated[time, PlainSerializer(lambda value: value.strftime("%H:%M"), return_type=str)]
MeetingModeValue = Literal["inPerson", "online"]


class CarePersonRefSchema(CamelModel):
    """Someone an entry is about: exactly one of the two ids (checked with a `people` code)."""

    member_id: int | None = None
    guest_id: int | None = None


class CareLogSourceInputSchema(CamelModel):
    """What the entry is logged from (rule 12): an attendance row (`reportId` and one of `memberId`,
    `guestId`), a report section (`reportId` and `section`) or a conversation thread (`conversationId`)."""

    kind: CareLogSourceKind
    report_id: int | None = None
    member_id: int | None = None
    guest_id: int | None = None
    section: ReportSection | None = None
    conversation_id: int | None = None


# The length limits are checked by the service, so a too-long text is a 422 with a `code`.
class CareLogCreateSchema(CamelModel):
    kind: CareLogKind
    status: CareLogStatus = CareLogStatus.DONE
    meeting_mode: MeetingModeValue | None = None
    occurred_on: date
    occurred_at_time: ClockTime | None = None
    people: list[CarePersonRefSchema]
    others: str | None = None
    participants: list[int] = Field(default_factory=list)
    heard_from: str | None = None
    text: str | None = None
    visibility: CareLogVisibility = CareLogVisibility.LEADERS
    source: CareLogSourceInputSchema | None = None


class CareLogUpdateSchema(CamelModel):
    """Every field of the create body, all optional: only what is sent changes. The status isn't edited
    (complete or cancel a plan instead) and the source never changes."""

    kind: CareLogKind | None = None
    status: CareLogStatus | None = None
    meeting_mode: MeetingModeValue | None = None
    occurred_on: date | None = None
    occurred_at_time: ClockTime | None = None
    people: list[CarePersonRefSchema] | None = None
    others: str | None = None
    participants: list[int] | None = None
    heard_from: str | None = None
    text: str | None = None
    visibility: CareLogVisibility | None = None
    source: CareLogSourceInputSchema | None = None


class CareLogCompleteSchema(CamelModel):
    text: str | None = None
    occurred_on: date | None = None


class CareLogCancelSchema(CamelModel):
    reason: str | None = None


class CareLogPersonSchema(CamelModel):
    # Exactly one of the two ids.
    member_id: int | None
    guest_id: int | None
    name: str
    # Whether the caller may open this person's page (report tags rule 12).
    viewable: bool


class CareLogParticipantSchema(CamelModel):
    member_id: int
    name: str


class CareLogAuthorSchema(CamelModel):
    member_id: int
    name: str


class CareLogSourceGroupSchema(CamelModel):
    id: int
    name: str


class CareLogSourceSchema(CamelModel):
    kind: CareLogSourceKind
    # Null when the caller can't open the source or it is gone.
    report_id: int | None
    meeting_date: date | None
    small_group: CareLogSourceGroupSchema | None
    # False when the caller can't open it ("A report note you don't have access to").
    visible: bool
    # Section sources only: `prayer`, `praise` or `followUp`.
    section: ReportSection | None = None
    # True when the report or thread was deleted.
    gone: bool


class CareLogEntrySchema(CamelModel):
    id: int
    kind: CareLogKind
    status: CareLogStatus
    meeting_mode: MeetingModeValue | None
    occurred_on: date
    occurred_at_time: ClockTime | None
    people: list[CareLogPersonSchema]
    others: str | None
    participants: list[CareLogParticipantSchema]
    heard_from: str | None
    # Null only for a plan with no purpose.
    text: str | None
    visibility: CareLogVisibility
    # Only on a cancelled entry.
    cancel_reason: str | None
    author: CareLogAuthorSchema
    source: CareLogSourceSchema | None
    # Planned, and its moment has passed in church time (`plan_past_due`): *Record how it went*.
    past_due: bool
    # The author edits and deletes; the author or a participant completes or cancels a plan.
    can_edit: bool
    can_complete: bool
    edited_at: datetime | None
    created_at: datetime


class CareAudienceBodySchema(CamelModel):
    """An entry not saved yet: who it is about, who may see it, and who is "with" (counts are checked with
    a `people` / `participants` code)."""

    people: list[CarePersonRefSchema] = Field(default_factory=list)
    visibility: CareLogVisibility = CareLogVisibility.LEADERS
    participants: list[int]


class CareAudienceGainSchema(CamelModel):
    member_id: int
    name: str


class CareAudienceSchema(CamelModel):
    # The participants who would see the entry only because they are named (rule 3), in the order sent.
    # Null: not known (auth-server couldn't be asked), so show no warning.
    gains: list[CareAudienceGainSchema] | None


class CareLogComingUpSchema(CamelModel):
    """The caller's own plans (care spec rule 11); no paging, the lists stay short."""

    # Planned and past due (`plan_past_due`: its time passed, or its day is over), oldest first.
    past_due: list[CareLogEntrySchema]
    # The rest, through the next 7 days, soonest first.
    upcoming: list[CareLogEntrySchema]


class CarePersonSearchRowSchema(CamelModel):
    """Only what tells people apart, like the tag search: no email, address, notes or attendance."""

    person: PersonSchema
    groups: list[TagSearchGroupSchema]
    # Guests only; null for members and for guests without 4 phone digits.
    phone_last4: str | None
