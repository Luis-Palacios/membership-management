from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StringConstraints

from membership_management.api.schemas.base import CamelModel
from membership_management.data.small_groups.models import SmallGroupRole, Weekday


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


class ReportRosterGroupSchema(CamelModel):
    id: int
    name: str
    meeting_address: str | None
    meeting_day: Weekday | None
    closed_at: date | None


class ReportRosterPersonSchema(CamelModel):
    member_id: int
    name: str
    role: SmallGroupRole
    joined_at: date
    missed_streak: int


class ReportRosterSchema(CamelModel):
    small_group: ReportRosterGroupSchema
    meeting_date: date
    church_sunday: date
    existing_report_id: int | None
    people: list[ReportRosterPersonSchema]


class ReportAttendanceInputSchema(CamelModel):
    member_id: int
    attended_group: bool
    attended_church: bool
    observation: Observation = None


class ReportBodySchema(CamelModel):
    """Create and edit body; an edit replaces the whole report."""

    meeting_date: date
    address: Address = None
    group_prayer_request: ReportText = None
    group_praise_report: ReportText = None
    group_relevant_discussion: ReportText = None
    attendances: list[ReportAttendanceInputSchema]


class ReportGroupSchema(CamelModel):
    id: int
    name: str
    meeting_address: str | None
    closed_at: date | None


class ReportPersonSchema(CamelModel):
    member_id: int
    name: str


class ReportAttendanceSchema(CamelModel):
    member_id: int
    name: str
    role: SmallGroupRole
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


class ReportPermissionsSchema(CamelModel):
    can_edit: bool
    can_delete: bool


class ReportDetailSchema(CamelModel):
    """Routes returning this use `response_model_exclude_unset=True` so rule 9 omits the keys outright."""

    id: int
    small_group: ReportGroupSchema
    meeting_date: date
    church_sunday: date
    address: str | None
    group_prayer_request: str | None
    group_praise_report: str | None
    group_relevant_discussion: str | None
    submitted_by: ReportPersonSchema
    submitted_at: datetime
    observations_visible: bool
    attendances: list[ReportAttendanceSchema]
    totals: ReportTotalsSchema
    permissions: ReportPermissionsSchema


class ReportListGroupSchema(CamelModel):
    id: int
    name: str
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


class NotFiledItemSchema(CamelModel):
    kind: Literal["notFiled"] = "notFiled"
    small_group: ReportListGroupSchema
    meeting_date: date


class ReportCountsSchema(CamelModel):
    all: int
    filed: int
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
    meeting_day: Weekday | None
    closed_at: date | None


class SummaryLastReportSchema(CamelModel):
    id: int
    meeting_date: date
    roster_count: int
    attended_group_count: int
    submitted_by: ReportPersonSchema


class ReportSummaryItemSchema(CamelModel):
    small_group: SummaryGroupSchema
    role: SmallGroupRole | None
    last_report: SummaryLastReportSchema | None
    not_filed_dates: list[date]
