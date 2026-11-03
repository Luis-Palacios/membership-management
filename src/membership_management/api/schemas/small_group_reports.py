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
    ReportStatus,
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
Observation = Annotated[
    Annotated[str, StringConstraints(max_length=1024)] | None, BeforeValidator(_blank_to_none)
]
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


class ReportStarterNameSchema(CamelModel):
    name: str


class ExistingReportSchema(CamelModel):
    """The report on the roster's date: a submitted report, a no meeting or a draft the caller sees."""

    id: int
    status: ReportStatus
    held: bool
    version: int


class HiddenDraftSchema(CamelModel):
    """A draft the caller can't see holds the date: no id, no content (report auto-save rule 17)."""

    status: Literal[ReportStatus.DRAFT] = ReportStatus.DRAFT
    started_by: ReportStarterNameSchema


class ReportRosterSchema(CamelModel):
    small_group: ReportRosterGroupSchema
    meeting_date: date
    church_sunday: date
    existing_report: ExistingReportSchema | HiddenDraftSchema | None
    # Submitted reports only, for clients from before auto-save. Gone in stage 6.
    existing_report_id: int | None
    existing_report_held: bool | None
    people: list[ReportRosterPersonSchema]


class ReportAttendanceInputSchema(CamelModel):
    """One person's line: `memberId` or `guestId`, exactly one."""

    member_id: int | None = None
    guest_id: int | None = None
    # Null only on a draft (report auto-save rule 4). The keys are still required.
    attended_group: bool | None
    attended_church: bool | None
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
    sections: ReportSectionsInputSchema
    attendances: list[ReportAttendanceInputSchema]
    # Create only; true on an edit is a 422.
    replaces_no_meeting: bool = False
    # Create only; an edit keeps the report's status, and submitting has its own route.
    status: ReportStatus = ReportStatus.SUBMITTED
    # Edit only: the version the save is based on (409 when the report has moved on).
    version: int | None = None


class NotHeldReportBodySchema(CamelModel):
    """Create and edit body of a no meeting: the group didn't meet on `meeting_date` (rule 13)."""

    model_config = ConfigDict(extra="forbid")

    held: Literal[False]
    meeting_date: date
    not_held_reason: ReportReason = None
    # Create only: replace the date's draft, which the caller must be able to see (report auto-save rule 18).
    replaces_draft: bool = False
    # Edit only: the version the save is based on (409 when the report has moved on).
    version: int | None = None


class ReportSubmitBodySchema(CamelModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = None


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
    # Null only while the report is a draft.
    attended_group: bool | None
    attended_church: bool | None
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


class TagSearchGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience
    role: SmallGroupRole


class TagSearchRowSchema(CamelModel):
    """Only what tells people apart (report tags rule 10): no email, address, notes or attendance."""

    person: PersonSchema
    in_this_group: bool
    groups: list[TagSearchGroupSchema]
    # Guests only; null for members and for guests without 4 phone digits.
    phone_last4: str | None


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
    # The church-wide no meeting week the report belongs to; a leader's edit of the reason or date unlinks it.
    no_meeting_week_id: int | None
    address: str | None
    sections: ReportSectionsSchema
    # Null on a draft.
    submitted_by: ReportPersonSchema | None
    submitted_at: datetime | None
    observations_visible: bool
    attendances: list[ReportAttendanceSchema]
    totals: ReportTotalsSchema
    permissions: ReportPermissionsSchema
    # Threads on this report: deleting the report deletes them too (the delete dialog says how many).
    conversation_count: int
    status: ReportStatus
    # Send it back on the next save or submit (report auto-save rule 9).
    version: int
    started_by: ReportPersonSchema
    started_at: datetime
    # Null member with a date: an unlinked admin's edit.
    last_edited_by: ReportPersonSchema | None
    last_edited_at: datetime | None


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
    no_meeting_week_id: int | None


class NotFiledItemSchema(CamelModel):
    kind: Literal["notFiled"] = "notFiled"
    small_group: ReportListGroupSchema
    meeting_date: date
    # A draft the caller can't see is in progress for this meeting; it still isn't filed (rule 15).
    has_draft: bool
    draft_started_by: ReportStarterNameSchema | None


class DraftItemSchema(CamelModel):
    """A draft the caller sees (report auto-save rule 14)."""

    kind: Literal["draft"] = "draft"
    id: int
    small_group: ReportListGroupSchema
    meeting_date: date
    started_by: ReportPersonSchema
    answered_count: int
    roster_count: int
    last_saved_at: datetime


class ReportCountsSchema(CamelModel):
    all: int
    filed: int
    not_held: int
    not_filed: int
    draft: int


class ReportListSchema(CamelModel):
    items: list[
        Annotated[FiledReportItemSchema | NotFiledItemSchema | DraftItemSchema, Field(discriminator="kind")]
    ]
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


class SummaryDraftSchema(CamelModel):
    id: int
    meeting_date: date
    answered_count: int
    roster_count: int
    last_saved_at: datetime


class ReportSummaryItemSchema(CamelModel):
    small_group: SummaryGroupSchema
    role: SmallGroupRole | None
    last_report: SummaryLastReportSchema | None
    not_filed_dates: list[date]
    has_leader: bool
    recent_meetings: list[RecentMeetingSchema]
    # The newest draft the caller sees (report auto-save rule 14).
    draft: SummaryDraftSchema | None


class NoMeetingWeekBodySchema(CamelModel):
    """Mark the church week containing `date` (any day of it) as no meeting for every open group."""

    model_config = ConfigDict(extra="forbid")

    date: date
    # Ignored when the week is already marked: a re-run keeps the week's reason.
    reason: ReportReason = None


class NoMeetingWeekReasonBodySchema(CamelModel):
    model_config = ConfigDict(extra="forbid")

    # Required: null clears the reason.
    reason: ReportReason


class NoMeetingWeekSchema(CamelModel):
    id: int
    week_start: date
    reason: str | None
    created_by: ReportPersonSchema
    created_at: datetime
    updated_at: datetime
    # Reports still linked to the week (a leader's edit or a held report unlinks or replaces one).
    linked_count: int


class NoMeetingWeekSkippedSchema(CamelModel):
    # Groups with any report dated in the week, held or not.
    reported: int
    no_meeting_day: int


class NoMeetingWeekMarkSchema(NoMeetingWeekSchema):
    # Created by this call.
    marked: int
    skipped: NoMeetingWeekSkippedSchema


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
    no_meeting_week_id: int | None
    submitted_by: ReportPersonSchema


class WeekGroupSchema(CamelModel):
    small_group: WeekSmallGroupSchema
    leaders: list[WeekLeaderSchema]
    status: Literal["submitted", "notHeld", "notFiled", "today", "upcoming", "noLeader", "noMeetingDay"]
    meeting_date: date | None
    reports: list[WeekReportSchema]
    # On `notFiled` and `today` rows only: a label, with no id or content (report auto-save rule 15).
    has_draft: bool


class ReportWeekSchema(CamelModel):
    week_start: date
    week_end: date
    today: date
    is_current_week: bool
    # Set when the week is marked church-wide.
    no_meeting_week: NoMeetingWeekSchema | None
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
    sections: ReportSectionsSchema
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
