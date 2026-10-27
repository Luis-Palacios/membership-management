from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from membership_management.api.access import (
    GuestScope,
    GuestScopeDep,
    MemberScope,
    MemberScopeDep,
    SmallGroupScope,
    SmallGroupScopeDep,
    comment_side,
    conversation_group_ids,
    leads_group,
    sees_all_observations,
)
from membership_management.api.church_time import church_today
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import (
    AuthClaims,
    CurrentClaimsDep,
    get_current_claims,
    has_permission,
    require_permission,
)
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.report_items import sections_input, sections_schema, viewable_tagged
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_group_reports import (
    FiledReportItemSchema,
    HeldReportBodySchema,
    NotFiledItemSchema,
    NotHeldReportBodySchema,
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
    ReportSharedEntrySchema,
    ReportSharedSchema,
    ReportStillToReportSchema,
    ReportSummaryItemSchema,
    ReportTotalsSchema,
    ReportWeekSchema,
    SharedConversationSchema,
    SharedSmallGroupSchema,
    SummaryGroupSchema,
    SummaryLastReportSchema,
    TagSearchGroupSchema,
    TagSearchRowSchema,
    WeekGroupSchema,
    WeekLeaderSchema,
    WeekReportSchema,
    WeekSmallGroupSchema,
)
from membership_management.data.small_groups.conversation_services import get_section_conversations
from membership_management.data.small_groups.models import SmallGroup
from membership_management.data.small_groups.results import (
    AttendanceInput,
    NotFiledMeeting,
    PersonKey,
    ReportDetail,
    ReportInput,
)
from membership_management.data.small_groups.services import (
    AttendanceMismatchError,
    FutureMeetingDateError,
    FutureWeekError,
    InactiveTagError,
    MemberRequiredToSubmitError,
    NotGroupLeaderOnDateError,
    ReportAlreadyExistsError,
    ReportItemsLimitError,
    ReportItemTooLongError,
    ReportKindChangeError,
    ReportStatus,
    SmallGroupClosedError,
    UnknownTagError,
    build_report_detail,
    church_sunday,
    create_report,
    delete_report,
    get_report,
    get_report_roster,
    get_report_shared,
    get_report_summary,
    get_report_week,
    get_small_group,
    list_reports,
    search_taggable_people,
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

    def __init__(self, existing_report_id: int, existing_report_held: bool) -> None:
        super().__init__(status_code=409, detail=DUPLICATE_REPORT_DETAIL)
        self.existing_report_id = existing_report_id
        self.existing_report_held = existing_report_held


def _small_group_or_404(db: MembersSessionDep, small_group_id: int, scope: SmallGroupScope) -> SmallGroup:
    """404 for a missing group and for one outside the scope, with the same message."""
    small_group = get_small_group(db, small_group_id) if scope.includes(small_group_id) else None
    if small_group is None:
        raise HTTPException(status_code=404, detail=f"Small group with ID {small_group_id} not found.")
    return small_group


def _http_error(exc: Exception) -> HTTPException:
    """Map a report domain error to its HTTP error (the staff app matches on status and `detail`)."""
    if isinstance(exc, ReportAlreadyExistsError):
        return DuplicateReportHTTPError(exc.existing_id, exc.existing_held)
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
    if isinstance(exc, ReportKindChangeError):
        return HTTPException(
            status_code=422,
            detail="A report can't change between a meeting and a no meeting. Delete it and add the other.",
        )
    if isinstance(exc, ReportItemsLimitError):
        return HTTPException(status_code=422, detail=f"Too many items or tags in {exc.section}.")
    if isinstance(exc, ReportItemTooLongError):
        return HTTPException(
            status_code=422,
            detail=f"An item in {exc.section} is too long: items can be up to 1024 characters.",
        )
    if isinstance(exc, UnknownTagError):
        return HTTPException(status_code=422, detail="Unknown person to tag.")
    if isinstance(exc, InactiveTagError):
        return HTTPException(status_code=422, detail=f"{exc.name} is inactive and can't be tagged.")
    raise exc


def _can_write_reports(claims: CurrentClaimsDep) -> None:
    """`smallGroupReports: create` or `update`: either is enough to tag (report tags rule 6)."""
    if not (
        has_permission(claims, "smallGroupReports", "create")
        or has_permission(claims, "smallGroupReports", "update")
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")


# The item errors a create or edit can raise (report tags rules 3 and 7).
_ITEM_ERRORS = (ReportItemsLimitError, ReportItemTooLongError, UnknownTagError, InactiveTagError)


@router.get(
    "/small-groups/{small_group_id}/report-roster",
    name="get_small_group_report_roster",
    description="Who goes in a report for a meeting date, plus the church Sunday and any existing report",
    dependencies=[Depends(require_permission("smallGroupReports", "view"))],
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
            audience=small_group.audience,
            meeting_address=small_group.meeting_address,
            meeting_day=small_group.meeting_day,
            closed_at=small_group.closed_at,
        ),
        meeting_date=meeting_date,
        church_sunday=church_sunday(meeting_date),
        existing_report_id=roster.existing_report_id,
        existing_report_held=roster.existing_report_held,
        people=[
            ReportRosterPersonSchema(
                person=_person(p.member_id, p.guest_id, p.name),
                name=p.name,
                role=p.role,
                joined_at=p.joined_at,
                missed_streak=p.missed_streak,
            )
            for p in roster.people
        ],
    )


@router.get(
    "/small-groups/{small_group_id}/tag-search",
    name="search_small_group_taggable_people",
    description="Active members and guests church-wide to tag in this group's reports, this group's first",
    dependencies=[Depends(_can_write_reports)],
)
def get_tag_search(
    small_group_id: int,
    db: MembersSessionDep,
    scope: SmallGroupScopeDep,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[TagSearchRowSchema]:
    small_group = _small_group_or_404(db, small_group_id, scope)
    return [
        TagSearchRowSchema(
            person=PersonSchema(type=row.person[0], id=row.person[1], name=row.name),
            in_this_group=row.in_this_group,
            groups=[
                TagSearchGroupSchema(id=g.id, name=g.name, audience=g.audience, role=g.role)
                for g in row.groups
            ],
            phone_last4=row.phone_last4,
        )
        for row in search_taggable_people(db, small_group, q)
    ]


def _person(member_id: int | None, guest_id: int | None, name: str) -> PersonSchema:
    if member_id is not None:
        return PersonSchema(type="member", id=member_id, name=name)
    if guest_id is not None:
        return PersonSchema(type="guest", id=guest_id, name=name)
    raise ValueError("a row needs a member or a guest")


def _to_input(body: HeldReportBodySchema | NotHeldReportBodySchema) -> ReportInput:
    if isinstance(body, NotHeldReportBodySchema):
        return ReportInput(
            meeting_date=body.meeting_date,
            address=None,
            group_prayer_request=None,
            group_praise_report=None,
            group_relevant_discussion=None,
            attendances=[],
            held=False,
            not_held_reason=body.not_held_reason,
        )
    return ReportInput(
        meeting_date=body.meeting_date,
        address=body.address,
        group_prayer_request=body.group_prayer_request,
        group_praise_report=body.group_praise_report,
        group_relevant_discussion=body.group_relevant_discussion,
        attendances=[
            AttendanceInput(a.member_id, a.guest_id, a.attended_group, a.attended_church, a.observation)
            for a in body.attendances
        ],
        replaces_no_meeting=body.replaces_no_meeting,
        sections=sections_input(body.sections) if body.sections is not None else None,
    )


def _detail_schema(detail: ReportDetail, viewable: frozenset[PersonKey]) -> ReportDetailSchema:
    """Map the service's detail. Observation keys are only passed when visible, so they stay unset
    (and are dropped by `response_model_exclude_unset`) when they aren't."""
    visible = detail.observations_visible
    open_group = detail.small_group_closed_at is None
    attendances = [
        ReportAttendanceSchema(
            person=_person(a.member_id, a.guest_id, a.name),
            name=a.name,
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
            audience=detail.small_group_audience,
            meeting_address=detail.small_group_meeting_address,
            closed_at=detail.small_group_closed_at,
        ),
        meeting_date=detail.meeting_date,
        church_sunday=church_sunday(detail.meeting_date),
        held=detail.held,
        not_held_reason=detail.not_held_reason,
        address=detail.address,
        group_prayer_request=detail.group_prayer_request,
        group_praise_report=detail.group_praise_report,
        group_relevant_discussion=detail.group_relevant_discussion,
        sections=sections_schema(detail.items, viewable),
        submitted_by=ReportPersonSchema(
            member_id=detail.submitted_by_member_id, name=detail.submitted_by_name
        ),
        submitted_at=detail.submitted_at,
        observations_visible=visible,
        attendances=attendances,
        totals=ReportTotalsSchema(**totals),
        permissions=ReportPermissionsSchema(can_edit=open_group, can_delete=open_group),
        conversation_count=detail.conversation_count,
    )


def _report_detail_or_404(
    db: MembersSessionDep,
    report_id: int,
    scope: SmallGroupScope,
    claims: AuthClaims,
    member_scope: MemberScope,
    guest_scope: GuestScope,
) -> ReportDetailSchema:
    """The report's detail as this caller may see it; 404 when missing or outside the scope."""
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    detail = build_report_detail(
        db,
        report,
        sees_all_observations=sees_all_observations(claims),
        leads_group=leads_group(scope, report.small_group_id),
    )
    return _detail_schema(detail, viewable_tagged(db, claims, detail.items, member_scope, guest_scope))


# Declared before `/small-group-reports/{report_id}` so "summary" is never read as a report id.
@router.get(
    "/small-group-reports",
    name="list_small_group_reports",
    description="Filed reports and not-filed meetings of the groups in scope, newest first, with counts",
    dependencies=[Depends(require_permission("smallGroupReports", "view"))],
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
            id=item.small_group_id,
            name=item.small_group_name,
            audience=item.small_group_audience,
            closed_at=item.small_group_closed_at,
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
                    held=item.held,
                    not_held_reason=item.not_held_reason,
                )
            )
    return ReportListSchema(
        items=items,
        counts=ReportCountsSchema(
            all=result.counts.all,
            filed=result.counts.filed,
            not_held=result.counts.not_held,
            not_filed=result.counts.not_filed,
        ),
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/small-group-reports/summary",
    name="get_small_group_reports_summary",
    description="Per open group in scope: the latest report and the meetings still without one",
    dependencies=[Depends(require_permission("smallGroupReports", "view"))],
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
                audience=row.group.audience,
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
                RecentMeetingSchema(date=m.date, report_id=m.report_id, held=m.held)
                for m in row.recent_meetings
            ],
        )
        for row in summary
    ]


@router.get(
    "/small-group-reports/week",
    name="get_small_group_reports_week",
    description="Every open group's report status for a Sunday-to-Saturday week",
    dependencies=[
        Depends(require_permission("smallGroups", "all")),
        Depends(require_permission("smallGroupReports", "viewObservations")),
    ],
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
                    id=g.group.id,
                    name=g.group.name,
                    audience=g.group.audience,
                    meeting_day=g.group.meeting_day,
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
                        held=r.held,
                        not_held_reason=r.not_held_reason,
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


@router.get(
    "/small-group-reports/shared",
    name="get_small_group_reports_shared",
    description="The week's prayer, praise and follow-up texts of groups in scope, and who's still to report",
    dependencies=[Depends(require_permission("smallGroupReports", "view"))],
)
def get_small_group_reports_shared(
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member_scope: MemberScopeDep,
    guest_scope: GuestScopeDep,
    week_date: Annotated[date | None, Query(alias="date")] = None,
) -> ReportSharedSchema:
    today = church_today()
    try:
        shared = get_report_shared(
            db,
            day=week_date if week_date is not None else today,
            today=today,
            only_group_ids=None if scope.full else scope.group_ids,
        )
    except FutureWeekError as exc:
        raise _http_error(exc) from exc
    # Only reports whose conversations the caller may see (`conversation_group_ids`): today that's the
    # whole scope, but a full scope without `viewObservations` gets none.
    audience = conversation_group_ids(claims, scope)
    conversations = get_section_conversations(
        db,
        frozenset(e.report_id for e in shared.entries if audience is None or e.small_group_id in audience),
        claims.sub,
        comment_side(claims),
    )
    # Decided once for everyone tagged in the week, not per entry.
    viewable = viewable_tagged(
        db, claims, [i for e in shared.entries for i in e.items], member_scope, guest_scope
    )
    return ReportSharedSchema(
        week_start=shared.week_start,
        week_end=shared.week_end,
        today=shared.today,
        is_current_week=shared.is_current_week,
        entries=[
            ReportSharedEntrySchema(
                report_id=e.report_id,
                meeting_date=e.meeting_date,
                small_group=SharedSmallGroupSchema(
                    id=e.small_group_id, name=e.small_group_name, audience=e.small_group_audience
                ),
                leaders=[
                    WeekLeaderSchema(member_id=l.member_id, name=l.name, role=l.role) for l in e.leaders
                ],
                prayer=e.prayer,
                praise=e.praise,
                follow_up=e.follow_up,
                sections=sections_schema(e.items, viewable),
                conversations={
                    section: SharedConversationSchema(
                        id=c.id,
                        status=c.status,
                        comment_count=c.comment_count,
                        unread=c.unread,
                        needs_my_reply=c.needs_my_reply,
                    )
                    for section, c in conversations.get(e.report_id, {}).items()
                },
            )
            for e in shared.entries
        ],
        still_to_report=[
            ReportStillToReportSchema(
                small_group=SharedSmallGroupSchema(
                    id=g.group.id, name=g.group.name, audience=g.group.audience
                ),
                status=g.status,
                meeting_date=g.meeting_date,
            )
            for g in shared.still_to_report
        ],
    )


@router.post(
    "/small-groups/{small_group_id}/reports",
    name="create_small_group_report",
    description="File the report of a meeting; the caller's member is recorded as the submitter",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_unset=True,
    dependencies=[
        Depends(require_permission("smallGroupReports", "create")),
        Depends(rate_limit("20/minute", scope="create_small_group_report")),
    ],
)
def post_small_group_report(
    small_group_id: int,
    body: ReportBodySchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
    member_scope: MemberScopeDep,
    guest_scope: GuestScopeDep,
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
        *_ITEM_ERRORS,
    ) as exc:
        raise _http_error(exc) from exc
    return _report_detail_or_404(db, report.id, scope, claims, member_scope, guest_scope)


@router.get(
    "/small-group-reports/{report_id}",
    name="get_small_group_report",
    description="A report with its attendance; observations only for viewObservations or the group's leaders",
    response_model_exclude_unset=True,
    dependencies=[Depends(require_permission("smallGroupReports", "view"))],
)
def get_small_group_report(
    report_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member_scope: MemberScopeDep,
    guest_scope: GuestScopeDep,
) -> ReportDetailSchema:
    return _report_detail_or_404(db, report_id, scope, claims, member_scope, guest_scope)


@router.patch(
    "/small-group-reports/{report_id}",
    name="update_small_group_report",
    description="Replace a report's content and attendance; the submitter and submission time never change",
    response_model_exclude_unset=True,
    dependencies=[
        Depends(require_permission("smallGroupReports", "update")),
        Depends(rate_limit("30/minute", scope="update_small_group_report")),
    ],
)
def patch_small_group_report(
    report_id: int,
    body: ReportBodySchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member_scope: MemberScopeDep,
    guest_scope: GuestScopeDep,
) -> ReportDetailSchema:
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    try:
        update_report(
            db,
            report,
            _to_input(body),
            sees_all_observations=sees_all_observations(claims),
            leads_group=leads_group(scope, report.small_group_id),
            today=church_today(),
        )
    except (
        SmallGroupClosedError,
        FutureMeetingDateError,
        ReportAlreadyExistsError,
        AttendanceMismatchError,
        ReportKindChangeError,
        *_ITEM_ERRORS,
    ) as exc:
        raise _http_error(exc) from exc
    return _report_detail_or_404(db, report_id, scope, claims, member_scope, guest_scope)


@router.delete(
    "/small-group-reports/{report_id}",
    name="delete_small_group_report",
    description="Delete a report and its attendance",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_permission("smallGroupReports", "delete")),
        Depends(rate_limit("20/minute", scope="delete_small_group_report")),
    ],
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
