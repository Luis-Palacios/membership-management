from dataclasses import dataclass
from datetime import date, time
from typing import Literal, NamedTuple

from membership_management.data.care.models import (
    CareLogKind,
    CareLogSourceKind,
    CareLogStatus,
    CareLogVisibility,
    MeetingMode,
)
from membership_management.data.small_groups.models import GroupAudience, ReportSection, ReportStatus
from membership_management.data.small_groups.results import PersonGroup, PersonKey


class CarePersonRow(NamedTuple):
    """A row of the people search: only what tells people apart (like the tag search)."""

    kind: Literal["member", "guest"]
    id: int
    name: str
    phone: str | None


class CarePerson(NamedTuple):
    person: PersonKey
    name: str
    # Open groups the person is active in today, by name.
    groups: list[PersonGroup]
    # Guests only: the last 4 digits of their phone, None when it has fewer.
    phone_last4: str | None


class SourceRef(NamedTuple):
    """What an entry was logged from, as far as it still exists (care spec rule 12)."""

    kind: CareLogSourceKind
    # False once the report or thread was deleted: the report fields are then None.
    exists: bool
    report_id: int | None
    meeting_date: date | None
    group_id: int | None
    group_name: str | None
    group_audience: GroupAudience | None
    report_status: ReportStatus | None
    # Attendance rows, follow-up and threads are observations: they follow the observation audience.
    # Prayer and praise only need the report's group in scope (reports rule 9).
    needs_observation_audience: bool
    # Section sources only.
    section: ReportSection | None = None


@dataclass(frozen=True)
class SourceInput:
    """The source of an entry being created, as the caller named it."""

    kind: CareLogSourceKind
    report_id: int | None = None
    person: PersonKey | None = None
    section: ReportSection | None = None
    conversation_id: int | None = None


@dataclass(frozen=True)
class CareLogFields:
    """The fields of an entry, as stored: what a create writes and what an edit leaves after merging."""

    kind: CareLogKind
    status: CareLogStatus
    meeting_mode: MeetingMode | None
    occurred_on: date
    occurred_at_time: time | None
    text: str | None
    heard_from: str | None
    others: str | None
    visibility: CareLogVisibility
    people: list[PersonKey]
    participants: list[int]
