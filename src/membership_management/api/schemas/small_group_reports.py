from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    Tag,
    model_validator,
)

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.person import PersonSchema
from membership_management.data.small_groups.models import (
    ConversationStatus,
    GroupAudience,
    ReportSection,
    SmallGroupRole,
    Weekday,
)
from membership_management.data.small_groups.results import StillToReportStatus


def _blank_to_none(value: object) -> object:
    """Trim text; whitespace-only becomes null (the columns are nullable, "" would be noise)."""
    if isinstance(value, str):
        return value.strip() or None
    return value


# Limits match the small_group_reports columns; observation is capped at 1024 by the contract.
Address = Annotated[Annotated[str, StringConstraints(max_length=255)] | None, BeforeValidator(_blank_to_none)]
ReportText = Annotated[
    Annotated[str, StringConstraints(max_length=1024)] | None, BeforeValidator(_blank_to_none)
]
Observation = ReportText
ReportReason = Annotated[
    Annotated[str, StringConstraints(max_length=255)] | None, BeforeValidator(_blank_to_none)
]


class ReportRosterGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None


class ReportRosterPersonSchema(CamelModel):
    person: PersonSchema
    name: str
    role: SmallGroupRole
    joined_at: date
    missed_streak: int


class ReportRosterSchema(CamelModel):
    small_group: ReportRosterGroupSchema
    meeting_date: date
    church_sunday: date
    existing_report_id: int | None
    existing_report_held: bool | None
    people: list[ReportRosterPersonSchema]


class ReportAttendanceInputSchema(CamelModel):
    """One person's line: `memberId` or `guestId`, exactly one."""

    member_id: int | None = None
    guest_id: int | None = None
    attended_group: bool
    attended_church: bool
    observation: Observation = None

    @model_validator(mode="after")
    def exactly_one_person(self) -> Self:
        if (self.member_id is None) == (self.guest_id is None):
            raise ValueError("Send either memberId or guestId.")
        return self


class TextSegmentInputSchema(CamelModel):
    type: Literal["text"]
    # Loose caps against oversized bodies; the item limits (report tags rule 3) are the service's.
    text: Annotated[str, StringConstraints(max_length=4096)]


class TaggedPersonInputSchema(CamelModel):
    type: Literal["member", "guest"]
    id: int


class PersonSegmentInputSchema(CamelModel):
    type: Literal["person"]
    person: TaggedPersonInputSchema


SegmentInputSchema = Annotated[TextSegmentInputSchema | PersonSegmentInputSchema, Field(discriminator="type")]


class ReportItemInputSchema(CamelModel):
    segments: Annotated[list[SegmentInputSchema], Field(max_length=200)]


SectionItemsInput = Annotated[list[ReportItemInputSchema], Field(max_length=100)]


class ReportSectionsInputSchema(CamelModel):
    """A held report's items by section; a missing key is an empty section."""

    prayer: SectionItemsInput = Field(default_factory=list)
    praise: SectionItemsInput = Field(default_factory=list)
    follow_up: SectionItemsInput = Field(default_factory=list)


class HeldReportBodySchema(CamelModel):
    """Create and edit body of a meeting that happened; an edit replaces the whole report."""

    held: Literal[True] = True
    meeting_date: date
    address: Address = None
    # Ignored when `sections` is sent; otherwise each line becomes an item (report tags rule 2).
    group_prayer_request: ReportText = None
    group_praise_report: ReportText = None
    group_relevant_discussion: ReportText = None
    sections: ReportSectionsInputSchema | None = None
    attendances: list[ReportAttendanceInputSchema]
    # Create only; true on an edit is a 422.
    replaces_no_meeting: bool = False


class NotHeldReportBodySchema(CamelModel):
    """Create and edit body of a no meeting: the group didn't meet on `meeting_date` (rule 13)."""

    model_config = ConfigDict(extra="forbid")

    held: Literal[False]
    meeting_date: date
    not_held_reason: ReportReason = None


def _report_kind(value: object) -> str:
    """Discriminator: a missing `held` means a held report, so clients from before no meeting still work."""
    held = value.get("held", True) if isinstance(value, dict) else getattr(value, "held", True)
    return "held" if held is not False else "notHeld"


ReportBodySchema = Annotated[
    Annotated[HeldReportBodySchema, Tag("held")] | Annotated[NotHeldReportBodySchema, Tag("notHeld")],
    Discriminator(_report_kind),
]


class ReportGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_address: str | None
    closed_at: date | None


class ReportPersonSchema(CamelModel):
    member_id: int
    name: str


class ReportAttendanceSchema(CamelModel):
    person: PersonSchema
    name: str
    role: SmallGroupRole
    # Null when the member's membership no longer covers the meeting date (memberships edited later).
    joined_at: date | None
    attended_group: bool
    attended_church: bool
    missed_streak: int
    # Left unset (so the key is omitted) when the viewer may not see observations (rule 9).
    observation: str | None = None


class ReportTotalsSchema(CamelModel):
    roster: int
    attended_group: int
    attended_church: int
    # Left unset (so the key is omitted) when the viewer may not see observations (rule 9).
    observations: int | None = None


class TaggedPersonSchema(PersonSchema):
    # Whether the caller may open the person's page (report tags rule 12).
    viewable: bool


class TextSegmentSchema(CamelModel):
    type: Literal["text"]
    text: str


class PersonSegmentSchema(CamelModel):
    type: Literal["person"]
    person: TaggedPersonSchema


SegmentSchema = Annotated[TextSegmentSchema | PersonSegmentSchema, Field(discriminator="type")]


class ReportItemSchema(CamelModel):
    id: int
    segments: list[SegmentSchema]


class ReportSectionsSchema(CamelModel):
    prayer: list[ReportItemSchema]
    praise: list[ReportItemSchema]
    follow_up: list[ReportItemSchema]


class ReportPermissionsSchema(CamelModel):
    can_edit: bool
    can_delete: bool


class ReportDetailSchema(CamelModel):
    """Routes returning this use `response_model_exclude_unset=True` so rule 9 omits the keys outright."""

    id: int
    small_group: ReportGroupSchema
    meeting_date: date
    church_sunday: date
    held: bool
    not_held_reason: str | None
    address: str | None
    # Derived from `sections` (one item per line, people by full name) until the old fields go away.
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    sections: ReportSectionsSchema
    submitted_by: ReportPersonSchema
    submitted_at: datetime
    observations_visible: bool
    attendances: list[ReportAttendanceSchema]
    totals: ReportTotalsSchema
    permissions: ReportPermissionsSchema
    # Threads on this report: deleting the report deletes them too (the delete dialog says how many).
    conversation_count: int


class ReportListGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    closed_at: date | None


class FiledReportItemSchema(CamelModel):
    kind: Literal["report"] = "report"
    id: int
    small_group: ReportListGroupSchema
    meeting_date: date
    submitted_by: ReportPersonSchema
    submitted_at: datetime
    roster_count: int
    attended_group_count: int
    attended_church_count: int
    held: bool
    not_held_reason: str | None


class NotFiledItemSchema(CamelModel):
    kind: Literal["notFiled"] = "notFiled"
    small_group: ReportListGroupSchema
    meeting_date: date


class ReportCountsSchema(CamelModel):
    all: int
    filed: int
    not_held: int
    not_filed: int


class ReportListSchema(CamelModel):
    items: list[Annotated[FiledReportItemSchema | NotFiledItemSchema, Field(discriminator="kind")]]
    counts: ReportCountsSchema
    total: int
    page: int
    page_size: int


class SummaryGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_day: Weekday | None
    closed_at: date | None


class SummaryLastReportSchema(CamelModel):
    id: int
    meeting_date: date
    roster_count: int
    attended_group_count: int
    submitted_by: ReportPersonSchema


class RecentMeetingSchema(CamelModel):
    date: date
    report_id: int | None
    held: bool | None


class ReportSummaryItemSchema(CamelModel):
    small_group: SummaryGroupSchema
    role: SmallGroupRole | None
    last_report: SummaryLastReportSchema | None
    not_filed_dates: list[date]
    has_leader: bool
    recent_meetings: list[RecentMeetingSchema]


class WeekSmallGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    meeting_day: Weekday | None


class WeekLeaderSchema(CamelModel):
    member_id: int
    name: str
    role: SmallGroupRole


class WeekReportSchema(CamelModel):
    id: int
    meeting_date: date
    roster_count: int
    attended_group_count: int
    attended_church_count: int
    observation_count: int
    held: bool
    not_held_reason: str | None
    submitted_by: ReportPersonSchema


class WeekGroupSchema(CamelModel):
    small_group: WeekSmallGroupSchema
    leaders: list[WeekLeaderSchema]
    status: Literal["submitted", "notHeld", "notFiled", "today", "upcoming", "noLeader", "noMeetingDay"]
    meeting_date: date | None
    reports: list[WeekReportSchema]


class ReportWeekSchema(CamelModel):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    groups: list[WeekGroupSchema]


class SharedSmallGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience


class SharedConversationSchema(CamelModel):
    """A section thread's indicator on a shared entry; `unread` and `needsMyReply` are the caller's."""

    id: int
    status: ConversationStatus
    comment_count: int
    unread: bool
    needs_my_reply: bool


class ReportSharedEntrySchema(CamelModel):
    report_id: int
    meeting_date: date
    small_group: SharedSmallGroupSchema
    leaders: list[WeekLeaderSchema]
    # null when empty after trimming.
    prayer: str | None
    praise: str | None
    follow_up: str | None
    # Section threads only, keyed by section; a key is absent when that section has no thread.
    conversations: dict[ReportSection, SharedConversationSchema]


class ReportStillToReportSchema(CamelModel):
    small_group: SharedSmallGroupSchema
    status: StillToReportStatus
    meeting_date: date


class ReportSharedSchema(CamelModel):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    entries: list[ReportSharedEntrySchema]
    still_to_report: list[ReportStillToReportSchema]
