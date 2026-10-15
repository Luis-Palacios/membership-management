from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import get_current_claims
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.small_groups import (
    SmallGroupCreateSchema,
    SmallGroupDetailSchema,
    SmallGroupMemberAddSchema,
    SmallGroupMemberRoleSchema,
    SmallGroupMemberSchema,
    SmallGroupSummarySchema,
    SmallGroupUpdateSchema,
)
from membership_management.data.small_groups.models import SmallGroup
from membership_management.data.small_groups.services import (
    ActiveMembershipNotFoundError,
    LeaderAlreadyExistsError,
    MemberAlreadyInGroupError,
    MemberNotFoundError,
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


def _get_or_404(db: MembersSessionDep, small_group_id: int) -> SmallGroup:
    small_group = get_small_group(db, small_group_id)
    if small_group is None:
        raise HTTPException(status_code=404, detail=f"Small group with ID {small_group_id} not found.")
    return small_group


@router.get("", name="list_small_groups", description="List all small groups, open and closed")
def get_small_groups(db: MembersSessionDep) -> list[SmallGroupSummarySchema]:
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
        for g in list_small_groups(db)
    ]


@router.get(
    "/{small_group_id}", name="get_small_group", description="Get a small group with its active members"
)
def get_small_group_detail(small_group_id: int, db: MembersSessionDep) -> SmallGroupDetailSchema:
    return _detail(db, _get_or_404(db, small_group_id))


@router.post(
    "",
    name="create_small_group",
    description="Create a small group",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("20/minute", scope="create_small_group"))],
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
    dependencies=[Depends(rate_limit("30/minute", scope="update_small_group"))],
)
def patch_small_group(
    small_group_id: int, body: SmallGroupUpdateSchema, db: MembersSessionDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id)
    changes = body.model_dump(exclude_unset=True)
    # name is NOT NULL: an explicit null would otherwise surface as a DB error (500).
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null.")
    return _detail(db, update_small_group(db, small_group, changes))


@router.post(
    "/{small_group_id}/close",
    name="close_small_group",
    description="Close a small group today and end all its active memberships",
    dependencies=[Depends(rate_limit("10/minute", scope="close_small_group"))],
)
def post_close_small_group(small_group_id: int, db: MembersSessionDep) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id)
    try:
        small_group = close_small_group(db, small_group, datetime.now(tz=UTC).date())
    except SmallGroupAlreadyClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is already closed.") from exc
    return _detail(db, small_group)


def _today() -> date:
    return datetime.now(tz=UTC).date()


@router.post(
    "/{small_group_id}/members",
    name="add_small_group_member",
    description="Add a member to a small group, joining today",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("30/minute", scope="add_small_group_member"))],
)
def post_small_group_member(
    small_group_id: int, body: SmallGroupMemberAddSchema, db: MembersSessionDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id)
    try:
        add_small_group_member(db, small_group, member_id=body.member_id, role=body.role, today=_today())
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Member with ID {body.member_id} not found.") from exc
    except MemberAlreadyInGroupError as exc:
        raise HTTPException(status_code=409, detail="This member is already in the small group.") from exc
    except LeaderAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="This small group already has a leader.") from exc
    return _detail(db, small_group)


@router.patch(
    "/{small_group_id}/members/{member_id}",
    name="change_small_group_member_role",
    description="Change a member's role; the previous period is kept as history",
    dependencies=[Depends(rate_limit("30/minute", scope="change_small_group_member_role"))],
)
def patch_small_group_member(
    small_group_id: int, member_id: int, body: SmallGroupMemberRoleSchema, db: MembersSessionDep
) -> SmallGroupDetailSchema:
    small_group = _get_or_404(db, small_group_id)
    try:
        change_small_group_member_role(db, small_group, member_id=member_id, role=body.role, today=_today())
    except SmallGroupClosedError as exc:
        raise HTTPException(status_code=409, detail="This small group is closed.") from exc
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This member is not in the small group.") from exc
    except LeaderAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="This small group already has a leader.") from exc
    return _detail(db, small_group)


@router.delete(
    "/{small_group_id}/members/{member_id}",
    name="remove_small_group_member",
    description="Remove a member by ending their membership today; the row is kept as history",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("30/minute", scope="remove_small_group_member"))],
)
def delete_small_group_member(small_group_id: int, member_id: int, db: MembersSessionDep) -> Response:
    small_group = _get_or_404(db, small_group_id)
    try:
        remove_small_group_member(db, small_group, member_id=member_id, today=_today())
    except ActiveMembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail="This member is not in the small group.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
