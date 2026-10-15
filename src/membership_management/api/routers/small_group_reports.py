from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from membership_management.api.access import SmallGroupScope, SmallGroupScopeDep
from membership_management.api.church_time import church_today
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import get_current_claims
from membership_management.api.rate_limit import default_user_rate_limit
from membership_management.api.schemas.small_group_reports import (
    ReportRosterGroupSchema,
    ReportRosterPersonSchema,
    ReportRosterSchema,
)
from membership_management.data.small_groups.models import SmallGroup
from membership_management.data.small_groups.services import (
    AttendanceMismatchError,
    FutureMeetingDateError,
    MemberRequiredToSubmitError,
    NotGroupLeaderOnDateError,
    ReportAlreadyExistsError,
    SmallGroupClosedError,
    church_sunday,
    get_report_roster,
    get_small_group,
)

# No prefix: report routes live under both /small-groups/{id}/... and /small-group-reports.
router = APIRouter(
    tags=["small-group-reports"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


DUPLICATE_REPORT_DETAIL = "There's already a report for this group on that date."


def _small_group_or_404(db: MembersSessionDep, small_group_id: int, scope: SmallGroupScope) -> SmallGroup:
    """404 for a missing group and for one outside the scope, with the same message."""
    small_group = get_small_group(db, small_group_id) if scope.includes(small_group_id) else None
    if small_group is None:
        raise HTTPException(status_code=404, detail=f"Small group with ID {small_group_id} not found.")
    return small_group


def _http_error(exc: Exception) -> HTTPException:
    """Map a report domain error to its HTTP error (the staff app matches on status and `detail`)."""
    if isinstance(exc, ReportAlreadyExistsError):
        return HTTPException(status_code=409, detail=DUPLICATE_REPORT_DETAIL)
    if isinstance(exc, MemberRequiredToSubmitError):
        return HTTPException(status_code=409, detail="Link your account to a member to submit reports.")
    if isinstance(exc, SmallGroupClosedError):
        return HTTPException(status_code=409, detail="This small group is closed.")
    if isinstance(exc, FutureMeetingDateError):
        return HTTPException(status_code=422, detail="The meeting date can't be in the future.")
    if isinstance(exc, AttendanceMismatchError):
        return HTTPException(
            status_code=422, detail="The attendance doesn't match the group's members on that date."
        )
    if isinstance(exc, NotGroupLeaderOnDateError):
        return HTTPException(status_code=422, detail="You didn't lead this group on that date.")
    raise exc


@router.get(
    "/small-groups/{small_group_id}/report-roster",
    name="get_small_group_report_roster",
    description="Who goes in a report for a meeting date, plus the church Sunday and any existing report",
)
def get_report_roster_for_date(
    small_group_id: int,
    meeting_date: Annotated[date, Query(alias="date")],
    db: MembersSessionDep,
    scope: SmallGroupScopeDep,
) -> ReportRosterSchema:
    small_group = _small_group_or_404(db, small_group_id, scope)
    try:
        roster = get_report_roster(db, small_group, meeting_date, today=church_today())
    except (SmallGroupClosedError, FutureMeetingDateError) as exc:
        raise _http_error(exc) from exc
    return ReportRosterSchema(
        small_group=ReportRosterGroupSchema(
            id=small_group.id,
            name=small_group.name,
            meeting_address=small_group.meeting_address,
            meeting_day=small_group.meeting_day,
            closed_at=small_group.closed_at,
        ),
        meeting_date=meeting_date,
        church_sunday=church_sunday(meeting_date),
        existing_report_id=roster.existing_report_id,
        people=[
            ReportRosterPersonSchema(
                member_id=p.member_id,
                name=p.member_name,
                role=p.role,
                joined_at=p.joined_at,
                missed_streak=p.missed_streak,
            )
            for p in roster.people
        ],
    )
