from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from membership_management.api.access import SmallGroupScope, SmallGroupScopeDep
from membership_management.api.church_time import church_today
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import get_current_claims, require_roles
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.small_group_reports import (
    FiledReportItemSchema,
    NotFiledItemSchema,
    RecentMeetingSchema,
    ReportAttendanceSchema,
    ReportBodySchema,
    ReportCountsSchema,
    ReportDetailSchema,
    ReportGroupSchema,
    ReportListGroupSchema,
    ReportListSchema,
    ReportPermissionsSchema,
    ReportPersonSchema,
    ReportRosterGroupSchema,
    ReportRosterPersonSchema,
    ReportRosterSchema,
    ReportSummaryItemSchema,
    ReportTotalsSchema,
    ReportWeekSchema,
    SummaryGroupSchema,
    SummaryLastReportSchema,
    WeekGroupSchema,
    WeekLeaderSchema,
    WeekReportSchema,
    WeekSmallGroupSchema,
)
from membership_management.data.small_groups.models import SmallGroup
from membership_management.data.small_groups.results import (
    AttendanceInput,
    NotFiledMeeting,
    ReportDetail,
    ReportInput,
)
from membership_management.data.small_groups.services import (
    AttendanceMismatchError,
    FutureMeetingDateError,
    FutureWeekError,
    MemberRequiredToSubmitError,
    NotGroupLeaderOnDateError,
    ReportAlreadyExistsError,
    ReportStatus,
    SmallGroupClosedError,
    build_report_detail,
    church_sunday,
    create_report,
    delete_report,
    get_report,
    get_report_roster,
    get_report_summary,
    get_report_week,
    get_small_group,
    list_reports,
    update_report,
)

# No prefix: report routes live under both /small-groups/{id}/... and /small-group-reports.
router = APIRouter(
    tags=["small-group-reports"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


# Default list window: the last six weeks.
DEFAULT_LIST_DAYS = 42

DUPLICATE_REPORT_DETAIL = "There's already a report for this group on that date."


class DuplicateReportHTTPError(HTTPException):
    """409 whose body also names the existing report (`existingReportId`); see its handler in `main.py`."""

    def __init__(self, existing_report_id: int) -> None:
        super().__init__(status_code=409, detail=DUPLICATE_REPORT_DETAIL)
        self.existing_report_id = existing_report_id


def _small_group_or_404(db: MembersSessionDep, small_group_id: int, scope: SmallGroupScope) -> SmallGroup:
    """404 for a missing group and for one outside the scope, with the same message."""
    small_group = get_small_group(db, small_group_id) if scope.includes(small_group_id) else None
    if small_group is None:
        raise HTTPException(status_code=404, detail=f"Small group with ID {small_group_id} not found.")
    return small_group


def _http_error(exc: Exception) -> HTTPException:
    """Map a report domain error to its HTTP error (the staff app matches on status and `detail`)."""
    if isinstance(exc, ReportAlreadyExistsError):
        return DuplicateReportHTTPError(exc.existing_id)
    if isinstance(exc, MemberRequiredToSubmitError):
        return HTTPException(status_code=409, detail="Link your account to a member to submit reports.")
    if isinstance(exc, SmallGroupClosedError):
        return HTTPException(status_code=409, detail="This small group is closed.")
    if isinstance(exc, FutureMeetingDateError):
        return HTTPException(status_code=422, detail="The meeting date can't be in the future.")
    if isinstance(exc, FutureWeekError):
        return HTTPException(status_code=422, detail="The week can't be in the future.")
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


def _to_input(body: ReportBodySchema) -> ReportInput:
    return ReportInput(
        meeting_date=body.meeting_date,
        address=body.address,
        group_prayer_request=body.group_prayer_request,
        group_praise_report=body.group_praise_report,
        group_relevant_discussion=body.group_relevant_discussion,
        attendances=[
            AttendanceInput(a.member_id, a.attended_group, a.attended_church, a.observation)
            for a in body.attendances
        ],
    )


def _detail_schema(detail: ReportDetail) -> ReportDetailSchema:
    """Map the service's detail. Observation keys are only passed when visible, so they stay unset
    (and are dropped by `response_model_exclude_unset`) when they aren't."""
    visible = detail.observations_visible
    open_group = detail.small_group_closed_at is None
    attendances = [
        ReportAttendanceSchema(
            member_id=a.member_id,
            name=a.member_name,
            role=a.role,
            joined_at=a.joined_at,
            attended_group=a.attended_group,
            attended_church=a.attended_church,
            missed_streak=a.missed_streak,
            **({"observation": a.observation} if visible else {}),
        )
        for a in detail.attendances
    ]
    totals: dict[str, int] = {
        "roster": len(attendances),
        "attended_group": sum(a.attended_group for a in detail.attendances),
        "attended_church": sum(a.attended_church for a in detail.attendances),
    }
    if visible:
        totals["observations"] = sum(a.observation is not None for a in detail.attendances)
    return ReportDetailSchema(
        id=detail.id,
        small_group=ReportGroupSchema(
            id=detail.small_group_id,
            name=detail.small_group_name,
            meeting_address=detail.small_group_meeting_address,
            closed_at=detail.small_group_closed_at,
        ),
        meeting_date=detail.meeting_date,
        church_sunday=church_sunday(detail.meeting_date),
        address=detail.address,
        group_prayer_request=detail.group_prayer_request,
        group_praise_report=detail.group_praise_report,
        group_relevant_discussion=detail.group_relevant_discussion,
        submitted_by=ReportPersonSchema(
            member_id=detail.submitted_by_member_id, name=detail.submitted_by_name
        ),
        submitted_at=detail.submitted_at,
        observations_visible=visible,
        attendances=attendances,
        totals=ReportTotalsSchema(**totals),
        permissions=ReportPermissionsSchema(can_edit=open_group, can_delete=open_group),
    )


def _report_detail_or_404(
    db: MembersSessionDep, report_id: int, scope: SmallGroupScope
) -> ReportDetailSchema:
    """The report's detail as this caller may see it; 404 when missing or outside the scope."""
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    return _detail_schema(
        build_report_detail(db, report, sees_all_observations=scope.full, viewer_member_id=scope.member_id)
    )


# Declared before `/small-group-reports/{report_id}` so "summary" is never read as a report id.
@router.get(
    "/small-group-reports",
    name="list_small_group_reports",
    description="Filed reports and not-filed meetings of the groups in scope, newest first, with counts",
)
def get_small_group_reports(
    db: MembersSessionDep,
    scope: SmallGroupScopeDep,
    small_group_id: Annotated[int | None, Query(alias="smallGroupId")] = None,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    status_filter: Annotated[ReportStatus, Query(alias="status")] = "all",
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
) -> ReportListSchema:
    today = church_today()
    result = list_reports(
        db,
        only_group_ids=None if scope.full else scope.group_ids,
        small_group_id=small_group_id,
        from_date=from_date if from_date is not None else today - timedelta(days=DEFAULT_LIST_DAYS),
        to_date=to_date if to_date is not None else today,
        status=status_filter,
        q=q,
        page=page,
        page_size=page_size,
        today=today,
    )
    items: list[FiledReportItemSchema | NotFiledItemSchema] = []
    for item in result.items:
        group = ReportListGroupSchema(
            id=item.small_group_id, name=item.small_group_name, closed_at=item.small_group_closed_at
        )
        if isinstance(item, NotFiledMeeting):
            items.append(NotFiledItemSchema(small_group=group, meeting_date=item.meeting_date))
        else:
            items.append(
                FiledReportItemSchema(
                    id=item.id,
                    small_group=group,
                    meeting_date=item.meeting_date,
                    submitted_by=ReportPersonSchema(
                        member_id=item.submitted_by_member_id, name=item.submitted_by_name
                    ),
                    submitted_at=item.submitted_at,
                    roster_count=item.roster_count,
                    attended_group_count=item.attended_group_count,
                    attended_church_count=item.attended_church_count,
                )
            )
    return ReportListSchema(
        items=items,
        counts=ReportCountsSchema(
            all=result.counts.all, filed=result.counts.filed, not_filed=result.counts.not_filed
        ),
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/small-group-reports/summary",
    name="get_small_group_reports_summary",
    description="Per open group in scope: the latest report and the meetings still without one",
)
def get_small_group_reports_summary(
    db: MembersSessionDep, scope: SmallGroupScopeDep
) -> list[ReportSummaryItemSchema]:
    summary = get_report_summary(
        db,
        only_group_ids=None if scope.full else scope.group_ids,
        member_id=scope.member_id,
        today=church_today(),
    )
    return [
        ReportSummaryItemSchema(
            small_group=SummaryGroupSchema(
                id=row.group.id,
                name=row.group.name,
                meeting_day=row.group.meeting_day,
                closed_at=row.group.closed_at,
            ),
            role=row.role,
            last_report=(
                SummaryLastReportSchema(
                    id=row.last_report.id,
                    meeting_date=row.last_report.meeting_date,
                    roster_count=row.last_report.roster_count,
                    attended_group_count=row.last_report.attended_group_count,
                    submitted_by=ReportPersonSchema(
                        member_id=row.last_report.submitted_by_member_id,
                        name=row.last_report.submitted_by_name,
                    ),
                )
                if row.last_report is not None
                else None
            ),
            not_filed_dates=row.not_filed_dates,
            has_leader=row.has_leader,
            recent_meetings=[
                RecentMeetingSchema(date=m.date, report_id=m.report_id) for m in row.recent_meetings
            ],
        )
        for row in summary
    ]


@router.get(
    "/small-group-reports/week",
    name="get_small_group_reports_week",
    description="Every open group's report status for a Sunday-to-Saturday week (admins and elders only)",
    dependencies=[Depends(require_roles("admin", "elder"))],
)
def get_small_group_reports_week(
    db: MembersSessionDep, week_date: Annotated[date | None, Query(alias="date")] = None
) -> ReportWeekSchema:
    today = church_today()
    try:
        week = get_report_week(db, day=week_date if week_date is not None else today, today=today)
    except FutureWeekError as exc:
        raise _http_error(exc) from exc
    return ReportWeekSchema(
        week_start=week.week_start,
        week_end=week.week_end,
        today=week.today,
        is_current_week=week.is_current_week,
        groups=[
            WeekGroupSchema(
                small_group=WeekSmallGroupSchema(
                    id=g.group.id, name=g.group.name, meeting_day=g.group.meeting_day
                ),
                leaders=[
                    WeekLeaderSchema(member_id=l.member_id, name=l.name, role=l.role) for l in g.leaders
                ],
                status=g.status,
                meeting_date=g.meeting_date,
                reports=[
                    WeekReportSchema(
                        id=r.id,
                        meeting_date=r.meeting_date,
                        roster_count=r.roster_count,
                        attended_group_count=r.attended_group_count,
                        attended_church_count=r.attended_church_count,
                        observation_count=r.observation_count,
                        submitted_by=ReportPersonSchema(
                            member_id=r.submitted_by_member_id, name=r.submitted_by_name
                        ),
                    )
                    for r in g.reports
                ],
            )
            for g in week.groups
        ],
    )


@router.post(
    "/small-groups/{small_group_id}/reports",
    name="create_small_group_report",
    description="File the report of a meeting; the caller's member is recorded as the submitter",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit("20/minute", scope="create_small_group_report"))],
)
def post_small_group_report(
    small_group_id: int,
    body: ReportBodySchema,
    db: MembersSessionDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ReportDetailSchema:
    small_group = _small_group_or_404(db, small_group_id, scope)
    try:
        if member is None:
            raise MemberRequiredToSubmitError
        report = create_report(
            db,
            small_group,
            _to_input(body),
            submitter_member_id=member.id,
            caller_is_scoped=not scope.full,
            today=church_today(),
        )
    except (
        MemberRequiredToSubmitError,
        SmallGroupClosedError,
        FutureMeetingDateError,
        ReportAlreadyExistsError,
        AttendanceMismatchError,
        NotGroupLeaderOnDateError,
    ) as exc:
        raise _http_error(exc) from exc
    return _report_detail_or_404(db, report.id, scope)


@router.get(
    "/small-group-reports/{report_id}",
    name="get_small_group_report",
    description="A report with its attendance; observations only for admins, elders and the submitter",
    response_model_exclude_unset=True,
)
def get_small_group_report(
    report_id: int, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> ReportDetailSchema:
    return _report_detail_or_404(db, report_id, scope)


@router.patch(
    "/small-group-reports/{report_id}",
    name="update_small_group_report",
    description="Replace a report's content and attendance; the submitter and submission time never change",
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit("30/minute", scope="update_small_group_report"))],
)
def patch_small_group_report(
    report_id: int, body: ReportBodySchema, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> ReportDetailSchema:
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    try:
        update_report(
            db,
            report,
            _to_input(body),
            sees_all_observations=scope.full,
            viewer_member_id=scope.member_id,
            today=church_today(),
        )
    except (
        SmallGroupClosedError,
        FutureMeetingDateError,
        ReportAlreadyExistsError,
        AttendanceMismatchError,
    ) as exc:
        raise _http_error(exc) from exc
    return _report_detail_or_404(db, report_id, scope)


@router.delete(
    "/small-group-reports/{report_id}",
    name="delete_small_group_report",
    description="Delete a report and its attendance",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("20/minute", scope="delete_small_group_report"))],
)
def delete_small_group_report(report_id: int, db: MembersSessionDep, scope: SmallGroupScopeDep) -> Response:
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    try:
        delete_report(db, report)
    except SmallGroupClosedError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
