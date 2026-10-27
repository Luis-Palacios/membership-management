"""The person timeline as the API sends it (report tags rules 21 to 23): query parameters and the response."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from membership_management.api.access import GuestScope, MemberScope, viewable_people
from membership_management.api.church_time import church_today
from membership_management.api.jwt_auth import AuthClaims
from membership_management.api.report_items import segment_schemas, tagged_in
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.person_timeline import (
    PersonTimelineSchema,
    TimelineAttendanceSchema,
    TimelineCountsSchema,
    TimelineGroupSchema,
    TimelineItemSchema,
    TimelineObservationSchema,
    TimelineRowSchema,
    TimelineSubmitterSchema,
)
from membership_management.data.small_groups.results import PersonKey, PersonTimeline, TimelineGroup
from membership_management.data.small_groups.timeline_services import TimelineRangeError, resolve_range


@dataclass(frozen=True)
class TimelineParams:
    """Validated query: either `latest`, or a resolved date range and an optional group."""

    from_date: date | None
    to_date: date | None
    small_group_id: int | None
    latest: int | None


def get_timeline_params(
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    small_group_id: Annotated[int | None, Query(alias="smallGroupId")] = None,
    latest: Annotated[int | None, Query(ge=1, le=10)] = None,
) -> TimelineParams:
    if latest is not None:
        if from_date is not None or to_date is not None or small_group_id is not None:
            raise HTTPException(
                status_code=422, detail="latest can't be combined with from, to or smallGroupId."
            )
        return TimelineParams(None, None, None, latest)
    try:
        start, end = resolve_range(from_date, to_date, today=church_today())
    except TimelineRangeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TimelineParams(start, end, small_group_id, None)


TimelineParamsDep = Annotated[TimelineParams, Depends(get_timeline_params)]


def _group(group: TimelineGroup) -> TimelineGroupSchema:
    return TimelineGroupSchema(id=group.id, name=group.name, audience=group.audience)


def timeline_schema(
    db: Session,
    claims: AuthClaims,
    person: PersonSchema,
    timeline: PersonTimeline,
    member_scope: MemberScope,
    guest_scope: GuestScope,
) -> PersonTimelineSchema:
    """Chips follow rule 12 for the caller; the person's own is viewable (the caller is on their page)."""
    own: PersonKey = (person.type, person.id)
    viewable = viewable_people(
        db,
        claims,
        tagged_in(item for row in timeline.rows for item in row.items),
        member_scope,
        guest_scope,
    ) | {own}
    return PersonTimelineSchema(
        person=person,
        from_date=timeline.from_date,
        to_date=timeline.to_date,
        earliest_date=timeline.earliest_date,
        groups=[_group(g) for g in timeline.groups],
        counts=TimelineCountsSchema(
            notes=timeline.counts.notes,
            prayer=timeline.counts.prayer,
            praise=timeline.counts.praise,
            follow_up=timeline.counts.follow_up,
        ),
        rows=[
            TimelineRowSchema(
                report_id=row.report_id,
                meeting_date=row.meeting_date,
                small_group=_group(row.small_group),
                attendance=TimelineAttendanceSchema(
                    role=row.attendance.role,
                    attended_group=row.attendance.attended_group,
                    attended_church=row.attendance.attended_church,
                )
                if row.attendance is not None
                else None,
                observation=TimelineObservationSchema(
                    text=row.observation.text,
                    submitted_by=TimelineSubmitterSchema(
                        member_id=row.observation.submitted_by_member_id,
                        name=row.observation.submitted_by_name,
                    ),
                )
                if row.observation is not None
                else None,
                items=[
                    TimelineItemSchema(
                        id=item.id, section=item.section, segments=segment_schemas(item.segments, viewable)
                    )
                    for item in row.items
                ],
            )
            for row in timeline.rows
        ],
    )
