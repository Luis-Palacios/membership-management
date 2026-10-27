from datetime import date

from pydantic import Field

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_group_reports import SegmentSchema
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


class PersonTimelineSchema(CamelModel):
    person: PersonSchema
    # Null with `latest`.
    from_date: date | None = Field(alias="from")
    to_date: date | None = Field(alias="to")
    # The oldest visible row's date, any group (for "Show 3 more months").
    earliest_date: date | None
    # Groups with at least one visible row, any date (the group filter).
    groups: list[TimelineGroupSchema]
    counts: TimelineCountsSchema
    rows: list[TimelineRowSchema]
