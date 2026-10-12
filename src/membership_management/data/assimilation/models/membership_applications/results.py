from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


class RecentMembershipApplications(NamedTuple):
    applications: Sequence[MembershipApplicationSummary]
    start_date: datetime
    end_date: datetime


class MembershipApplicationSummary(NamedTuple):
    id: int
    person_id: int
    generated_date: datetime
    fulfilment_date: datetime | None
    first_name: str
    last_name: str

class MembershipApplicationDetails(NamedTuple):
    id: int
    person_id: int
    generated_date: datetime
    fulfilment_date: datetime | None
    first_name: str
    last_name: str
    life_before: str
    conversion: str
    life_after: str


class MostRecentMembershipApplication(NamedTuple):
    generated_date: datetime
    id: int
