from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status

from membership_management.api.access import (
    SmallGroupScope,
    SmallGroupScopeDep,
    ensure_caller_can_add_member,
    ensure_caller_can_change_member,
    ensure_guest_groups_enabled,
)
from membership_management.api.church_time import church_today
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import (
    CurrentClaimsDep,
    get_current_claims,
    has_permission,
    require_permission,
)
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.person import PersonSchema
from membership_management.api.schemas.small_groups import (
    SmallGroupCreateSchema,
    SmallGroupDetailSchema,
    SmallGroupGuestAddedSchema,
    SmallGroupGuestAddSchema,
    SmallGroupLeaderSchema,
    SmallGroupLeaveSchema,
    SmallGroupMemberAddSchema,
    SmallGroupMemberRoleSchema,
    SmallGroupMemberSchema,
    SmallGroupSummarySchema,
    SmallGroupUpdateSchema,
)
from membership_management.data.guests.services import InvitedByNotFoundError, NewGuest
from membership_management.data.small_groups.models import GroupAudience, SmallGroup, SmallGroupRole
from membership_management.data.small_groups.results import OtherGroup
from membership_management.data.small_groups.services import (
    ActiveMembershipNotFoundError,
    GuestAlreadyInGroupError,
    GuestInAnotherGroupError,
    GuestNotFoundError,
    GuestPeriodOverlapError,
    JoinedInFutureError,
    LeaderAlreadyExistsError,
    LeftInFutureError,
    LeftTooEarlyError,
    MemberAlreadyInGroupError,
    MemberNotFoundError,
    MembershipOverlapError,
    NotGuestGroupError,
    SmallGroupAlreadyClosedError,
    SmallGroupClosedError,
    add_guest_to_group,
    add_small_group_member,
    change_small_group_member_role,
    close_small_group,
    create_small_group,
    get_small_group,
    get_small_group_active_guests,
    get_small_group_active_members,
    list_small_groups,
    remove_guest_from_group,
    remove_small_group_member,
    set_small_group_leader,
    update_small_group,
)

router = APIRouter(
    prefix="/small-groups",
    tags=["small-groups"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


class GuestInAnotherGroupHTTPError(HTTPException):
    """409 whose body also names the guest's other group (`otherGroup`); see its handler in `main.py`.

    Only the id, name and join date are exposed: the caller may not have that group in scope (rule 7).
    """

    def __init__(self, other_group: OtherGroup) -> None:
        super().__init__(status_code=409, detail="This guest is in another group.")
        self.other_group = other_group


GUEST_JOIN_ERRORS = (
    SmallGroupClosedError,
    NotGuestGroupError,
    GuestNotFoundError,
    InvitedByNotFoundError,
    GuestAlreadyInGroupError,
    GuestInAnotherGroupError,
    JoinedInFutureError,
    GuestPeriodOverlapError,
)


def guest_join_http_error(exc: Exception) -> HTTPException:
    """Map the errors of `add_guest_to_group` to HTTP (the staff app matches on a phrase in `detail`)."""
    if isinstance(exc, GuestInAnotherGroupError):
        return GuestInAnotherGroupHTTPError(exc.other_group)
    errors: dict[type[Exception], tuple[int, str]] = {
        SmallGroupClosedError: (409, "This small group is closed."),
        NotGuestGroupError: (422, "Only a guest group can have guests."),
        GuestNotFoundError: (404, "Guest not found."),
        InvitedByNotFoundError: (404, "Inviting member not found."),
        GuestAlreadyInGroupError: (409, "This guest is already in the small group."),
        JoinedInFutureError: (422, "The join date can't be in the future."),
        GuestPeriodOverlapError: (409, "The join date overlaps an earlier period of this guest."),
    }
    status_code, detail = errors[type(exc)]
    return HTTPException(status_code=status_code, detail=detail)


def _detail(db: MembersSessionDep, small_group: SmallGroup) -> SmallGroupDetailSchema:
    members = get_small_group_active_members(db, small_group.id)
    rows = [
        SmallGroupMemberSchema(
            person=PersonSchema(type="member", id=m.member_id, name=m.member_name),
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in members
    ]
    guests = (
        get_small_group_active_guests(db, small_group.id, today=_today())
        if small_group.audience == GroupAudience.GUESTS
        else []
    )
    # Guests are plain participants, listed after the members (leaders and co-leaders first among those).
    rows += [
        SmallGroupMemberSchema(
            person=PersonSchema(type="guest", id=g.guest_id, name=g.guest_name),
            role=SmallGroupRole.MEMBER,
            joined_at=g.joined_at,
            missed_streak=standing.missed_streak,
            last_attended_date=standing.last_attended_date,
        )
        for g, standing in guests
    ]
    return SmallGroupDetailSchema(
        id=small_group.id,
        name=small_group.name,
        audience=small_group.audience,
        meeting_address=small_group.meeting_address,
        meeting_day=small_group.meeting_day,
        closed_at=small_group.closed_at,
        member_count=len(members),
        guest_count=len(guests),
        members=rows,
    )


def _get_or_404(db: MembersSessionDep, small_group_id: int, scope: SmallGroupScope) -> SmallGroup:
    """404 when the group doesn't exist or is outside the scope, with the same message for both."""
    small_group = get_small_group(db, small_group_id) if scope.includes(small_group_id) else None
    if small_group is None:
        raise HTTPException(status_code=404, detail=f"Small group with ID {small_group_id} not found.")
    return small_group


@router.get("", name="list_small_groups", description="List all small groups, open and closed")
def get_small_groups(db: MembersSessionDep, scope: SmallGroupScopeDep) -> list[SmallGroupSummarySchema]:
    return [
        SmallGroupSummarySchema(
            id=g.id,
            name=g.name,
            audience=g.audience,
            meeting_address=g.meeting_address,
            meeting_day=g.meeting_day,
            closed_at=g.closed_at,
            active_member_count=g.active_member_count,
            active_guest_count=g.active_guest_count,
            leader_member_id=g.leader_member_id,
            leader_name=g.leader_name,
        )
        for g in list_small_groups(db, None if scope.full else scope.group_ids)
    ]


@router.get(
    "/{small_group_id}", name="get_small_group", description="Get a small group with its active members"
)
def get_small_group_detail(
    small_group_id: int, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> SmallGroupDetailSchema:
    return _detail(db, _get_or_404(db, small_group_id, scope))


@router.post(
    "",
    name="create_small_group",
    description="Create a small group",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("smallGroups", "create")),
        Depends(rate_limit("20/minute", scope="create_small_group")),
    ],
)
def post_small_group(body: SmallGroupCreateSchema, db: MembersSessionDep) -> SmallGroupDetailSchema:
    if body.audience == GroupAudience.GUESTS:
        ensure_guest_groups_enabled()
    small_group = create_small_group(
        db,
        name=body.name,
        meeting_address=body.meeting_address,
        meeting_day=body.meeting_day,
        audience=body.audience,
    )
    return _detail(db, small_group)


@router.patch(
    "/{small_group_id}",
    name="update_small_group",
    description="Update the given fields of a small group",
    dependencies=[
        Depends(require_permission("smallGroups", "update")),
        Depends(rate_limit("30/minute", scope="update_small_group")),
    ],
)
def patch_small_group(
    small_group_id: int, body: SmallGroupUpdateSchema, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    # Refused even when it equals the current value: a group's audience is not editable at all.
    if "audience" in body.model_fields_set:
        raise HTTPException(status_code=422, detail="A group's audience can't be changed.")
    changes = body.model_dump(exclude_unset=True)
    # name is NOT NULL: an explicit null would otherwise surface as a DB error (500).
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null.")
    try:
        small_group = update_small_group(db, small_group, changes)
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    return _detail(db, small_group)


@router.post(
    "/{small_group_id}/close",
    name="close_small_group",
    description="Close a small group today and end all its active memberships",
    dependencies=[
        Depends(require_permission("smallGroups", "close")),
        Depends(rate_limit("10/minute", scope="close_small_group")),
    ],
)
def post_close_small_group(
    small_group_id: int, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    try:
        small_group = close_small_group(db, small_group, _today())
    except SmallGroupAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is already closed.") from exc
    return _detail(db, small_group)


def _today() -> date:
    return church_today()


@router.post(
    "/{small_group_id}/members",
    name="add_small_group_member",
    description="Add a member to a small group, joining on joinedAt (default today)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("smallGroups", "manageMembers")),
        Depends(rate_limit("30/minute", scope="add_small_group_member")),
    ],
)
def post_small_group_member(
    small_group_id: int,
    body: SmallGroupMemberAddSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    ensure_caller_can_add_member(claims, body.role)
    try:
        add_small_group_member(
            db,
            small_group,
            member_id=body.member_id,
            role=body.role,
            today=_today(),
            joined_at=body.joined_at,
        )
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Member with ID {body.member_id} not found.") from exc
    except MemberAlreadyInGroupError as exc:
        raise HTTPException(status_code=409, detail="This member is already in the small group.") from exc
    except LeaderAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="This small group already has a leader.") from exc
    except JoinedInFutureError as exc:
        raise HTTPException(status_code=422, detail="The join date can't be in the future.") from exc
    except MembershipOverlapError as exc:
        raise HTTPException(
            status_code=409, detail="The join date overlaps an earlier period of this member in the group."
        ) from exc
    return _detail(db, small_group)


@router.patch(
    "/{small_group_id}/members/{member_id}",
    name="change_small_group_member_role",
    description="Change a member's role; the previous period is kept as history",
    dependencies=[
        Depends(require_permission("smallGroups", "manageMembers")),
        Depends(rate_limit("30/minute", scope="change_small_group_member_role")),
    ],
)
def patch_small_group_member(
    small_group_id: int,
    member_id: int,
    body: SmallGroupMemberRoleSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    ensure_caller_can_change_member(db, claims, scope, small_group_id, member_id, body.role)
    try:
        change_small_group_member_role(db, small_group, member_id=member_id, role=body.role, today=_today())
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This member is not in the small group.") from exc
    except LeaderAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="This small group already has a leader.") from exc
    return _detail(db, small_group)


@router.put(
    "/{small_group_id}/leader",
    name="set_small_group_leader",
    description="Make a member the leader; any current leader becomes co-leader, in one transaction",
    dependencies=[
        Depends(require_permission("smallGroups", "setLeader")),
        Depends(rate_limit("30/minute", scope="set_small_group_leader")),
    ],
)
def put_small_group_leader(
    small_group_id: int, body: SmallGroupLeaderSchema, db: MembersSessionDep, scope: SmallGroupScopeDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    try:
        set_small_group_leader(db, small_group, member_id=body.member_id, today=_today())
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Member with ID {body.member_id} not found.") from exc
    except LeaderAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="This small group already has a leader.") from exc
    return _detail(db, small_group)


@router.delete(
    "/{small_group_id}/members/{member_id}",
    name="remove_small_group_member",
    description="Remove a member by ending their membership today; the row is kept as history",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_permission("smallGroups", "manageMembers")),
        Depends(rate_limit("30/minute", scope="remove_small_group_member")),
    ],
)
def delete_small_group_member(
    small_group_id: int,
    member_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    body: SmallGroupLeaveSchema | None = None,
) -> Response:
    small_group = _get_or_404(db, small_group_id, scope)
    ensure_caller_can_change_member(db, claims, scope, small_group_id, member_id, None)
    # Only the reason applies to a member: they leave today (a back-dated leave is for guests' reports).
    if body is not None and body.left_at is not None:
        raise HTTPException(status_code=422, detail="leftAt is only accepted when removing a guest.")
    try:
        remove_small_group_member(
            db,
            small_group,
            member_id=member_id,
            today=_today(),
            left_reason=body.left_reason if body is not None else None,
        )
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This member is not in the small group.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{small_group_id}/guests",
    name="add_small_group_guest",
    description="Add a guest (existing, or new) to a guest group, moving them if they are in another one",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("smallGroups", "manageMembers")),
        Depends(rate_limit("30/minute", scope="add_small_group_guest")),
    ],
)
def post_small_group_guest(
    small_group_id: int,
    body: SmallGroupGuestAddSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    member: CurrentMemberDep,
    scope: SmallGroupScopeDep,
) -> SmallGroupGuestAddedSchema:
    small_group = _get_or_404(db, small_group_id, scope)
    new_guest = None
    if body.new_guest is not None:
        # Permission first, then the setting: a caller who can't create guests learns nothing about it.
        if not has_permission(claims, "guests", "create"):
            raise HTTPException(status_code=403, detail="You don't have permission to do this.")
        ensure_guest_groups_enabled()
        new_guest = NewGuest(**body.new_guest.model_dump())
    try:
        guest_id = add_guest_to_group(
            db,
            small_group,
            guest_id=body.guest_id,
            new_guest=new_guest,
            joined_at=body.joined_at,
            move_from_other_group=body.move_from_other_group,
            created_by_member_id=member.id if member is not None else None,
            today=_today(),
        )
    except GUEST_JOIN_ERRORS as exc:
        raise guest_join_http_error(exc) from exc
    return SmallGroupGuestAddedSchema(**_detail(db, small_group).model_dump(), guest_id=guest_id)


@router.delete(
    "/{small_group_id}/guests/{guest_id}",
    name="remove_small_group_guest",
    description="End a guest's period in a group (today, or leftAt); the row is kept as history",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_permission("smallGroups", "manageMembers")),
        Depends(rate_limit("30/minute", scope="remove_small_group_guest")),
    ],
)
def delete_small_group_guest(
    small_group_id: int,
    guest_id: int,
    db: MembersSessionDep,
    scope: SmallGroupScopeDep,
    body: SmallGroupLeaveSchema | None = None,
) -> Response:
    small_group = _get_or_404(db, small_group_id, scope)
    try:
        remove_guest_from_group(
            db,
            small_group,
            guest_id=guest_id,
            left_reason=body.left_reason if body is not None else None,
            left_at=body.left_at if body is not None else None,
            today=_today(),
        )
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This guest is not in the small group.") from exc
    except LeftInFutureError as exc:
        raise HTTPException(status_code=422, detail="The leave date can't be in the future.") from exc
    except LeftTooEarlyError as exc:
        raise HTTPException(
            status_code=422,
            detail="The leave date can't be before the guest joined or before a report that has them.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
