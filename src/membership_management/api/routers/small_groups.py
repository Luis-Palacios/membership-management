from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status

from membership_management.api.access import (
    SmallGroupScope,
    SmallGroupScopeDep,
    ensure_caller_can_add_member,
    ensure_caller_can_change_member,
)
from membership_management.api.church_time import church_today
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep, get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.small_groups import (
    SmallGroupCreateSchema,
    SmallGroupDetailSchema,
    SmallGroupLeaderSchema,
    SmallGroupMemberAddSchema,
    SmallGroupMemberRoleSchema,
    SmallGroupMemberSchema,
    SmallGroupSummarySchema,
    SmallGroupUpdateSchema,
)
from membership_management.data.small_groups.models import SmallGroup
from membership_management.data.small_groups.services import (
    ActiveMembershipNotFoundError,
    JoinedInFutureError,
    LeaderAlreadyExistsError,
    MemberAlreadyInGroupError,
    MemberNotFoundError,
    MembershipOverlapError,
    SmallGroupAlreadyClosedError,
    SmallGroupClosedError,
    add_small_group_member,
    change_small_group_member_role,
    close_small_group,
    create_small_group,
    get_small_group,
    get_small_group_active_members,
    list_small_groups,
    remove_small_group_member,
    set_small_group_leader,
    update_small_group,
)

router = APIRouter(
    prefix="/small-groups",
    tags=["small-groups"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


def _detail(db: MembersSessionDep, small_group: SmallGroup) -> SmallGroupDetailSchema:
    members = get_small_group_active_members(db, small_group.id)
    return SmallGroupDetailSchema(
        id=small_group.id,
        name=small_group.name,
        meeting_address=small_group.meeting_address,
        meeting_day=small_group.meeting_day,
        closed_at=small_group.closed_at,
        members=[
            SmallGroupMemberSchema(
                member_id=m.member_id,
                member_name=m.member_name,
                role=m.role,
                joined_at=m.joined_at,
            )
            for m in members
        ],
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
            meeting_address=g.meeting_address,
            meeting_day=g.meeting_day,
            closed_at=g.closed_at,
            active_member_count=g.active_member_count,
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
    small_group = create_small_group(
        db, name=body.name, meeting_address=body.meeting_address, meeting_day=body.meeting_day
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
) -> Response:
    small_group = _get_or_404(db, small_group_id, scope)
    ensure_caller_can_change_member(db, claims, scope, small_group_id, member_id, None)
    try:
        remove_small_group_member(db, small_group, member_id=member_id, today=_today())
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This member is not in the small group.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
