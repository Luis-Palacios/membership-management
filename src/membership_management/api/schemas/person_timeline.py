from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.care_log import CareLogEntrySchema
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_group_reports import SegmentSchema
from membership_management.data.guests.models import GuestInactiveReason, GuestStatus
from membership_management.data.members.models import MemberInactiveReason, MemberStatus
from membership_management.data.small_groups.models import GroupAudience, ReportSection, SmallGroupRole


class TimelineGroupSchema(CamelModel):
    id: int
    name: str
    audience: GroupAudience


class TimelineAttendanceSchema(CamelModel):
    # The person's role in the group on the meeting date; null when no membership period covers it.
    role: SmallGroupRole | None
    attended_group: bool
    attended_church: bool


class TimelineSubmitterSchema(CamelModel):
    member_id: int
    name: str


class TimelineObservationSchema(CamelModel):
    text: str
    submitted_by: TimelineSubmitterSchema


class TimelineItemSchema(CamelModel):
    id: int
    section: ReportSection
    segments: list[SegmentSchema]


class TimelineRowSchema(CamelModel):
    report_id: int
    meeting_date: date
    small_group: TimelineGroupSchema
    # Null when the person isn't on the list, or the caller isn't in the report's observation audience.
    attendance: TimelineAttendanceSchema | None
    observation: TimelineObservationSchema | None
    # Only the items that tag this person, by section then position.
    items: list[TimelineItemSchema]


class TimelineCountsSchema(CamelModel):
    notes: int
    prayer: int
    praise: int
    follow_up: int
    # Care log entries listed, planned ones still ahead included. The four above count reports only.
    care_log: int


class TimelineReportEntrySchema(CamelModel):
    kind: Literal["report"] = "report"
    date: date
    report: TimelineRowSchema


class TimelineChangedBySchema(CamelModel):
    member_id: int
    name: str


class TimelineStatusEntrySchema(CamelModel):
    kind: Literal["status"] = "status"
    # The date they left; the day of reactivation.
    date: date
    status: MemberStatus | GuestStatus
    # The member or guest reasons, by person type; null when `status` is active.
    reason: MemberInactiveReason | GuestInactiveReason | None
    note: str | None
    # The member linked to whoever made the change; null when there is none.
    changed_by: TimelineChangedBySchema | None


class TimelineCareLogEntrySchema(CamelModel):
    """A care log entry about the person (care spec rule 13): planned ones carry `status: planned` (the
    *Planned* badge), and those still ahead are listed whatever the range."""

    kind: Literal["careLog"] = "careLog"
    # The day it happened or is planned for.
    date: date
    entry: CareLogEntrySchema


# staff-app skips a `kind` it doesn't know, so a new source can ship before the UI draws it (rule 15).
TimelineEntrySchema = Annotated[
    TimelineReportEntrySchema | TimelineStatusEntrySchema | TimelineCareLogEntrySchema,
    Field(discriminator="kind"),
]


class PersonTimelineSchema(CamelModel):
    person: PersonSchema
    # Null with `latest`.
    from_date: date | None = Field(alias="from")
    to_date: date | None = Field(alias="to")
    # The oldest visible entry's date, any kind and group (for "Show 3 more months").
    earliest_date: date | None
    # Groups with at least one visible report, any date (the group filter).
    groups: list[TimelineGroupSchema]
    # The report entries below, and the care log ones in `careLog`: status entries aren't counted.
    counts: TimelineCountsSchema
    # Newest first, every kind; on a date, status entries go above care log entries, above reports.
    entries: list[TimelineEntrySchema]
