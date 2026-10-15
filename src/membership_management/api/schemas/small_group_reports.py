from datetime import date

from membership_management.api.schemas.base import CamelModel
from membership_management.data.small_groups.models import SmallGroupRole, Weekday


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
