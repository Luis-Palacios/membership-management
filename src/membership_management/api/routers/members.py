from fastapi import APIRouter, Depends, HTTPException, status

from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.members import (
    MemberCreateSchema,
    MemberDetailSchema,
    MemberSmallGroupSchema,
    MemberSummarySchema,
    MemberUpdateSchema,
    MemberUserLinkSchema,
)
from membership_management.data.members.models import Member
from membership_management.data.members.services import (
    DuplicateMemberEmailError,
    MemberAlreadyLinkedError,
    UserAlreadyLinkedError,
    create_member,
    get_member,
    get_member_small_groups,
    link_member_user,
    list_members,
    unlink_member_user,
    update_member,
)

router = APIRouter(
    prefix="/members",
    tags=["members"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


def _detail(db: MembersSessionDep, member: Member) -> MemberDetailSchema:
    small_groups = get_member_small_groups(db, member.id)
    return MemberDetailSchema(
        id=member.id,
        name=member.name,
        email=member.email,
        phone=member.phone,
        address=member.address,
        birth_date=member.birth_date,
        sex=member.sex,
        user_id=member.user_id,
        small_groups=[
            MemberSmallGroupSchema(
                small_group_id=group.small_group_id,
                small_group_name=group.small_group_name,
                role=group.role,
                joined_at=group.joined_at,
            )
            for group in small_groups
        ],
    )


@router.get(
    "",
    name="list_members",
    description="List all members, with email and phone",
    dependencies=[Depends(require_permission("members", "view", "all"))],
)
def get_members(db: MembersSessionDep) -> list[MemberSummarySchema]:
    return [
        MemberSummarySchema(id=m.id, name=m.name, email=m.email, phone=m.phone, user_id=m.user_id)
        for m in list_members(db)
    ]


@router.get(
    "/{member_id}",
    name="get_member",
    description="Get a member with their current small groups",
    dependencies=[Depends(require_permission("members", "view", "all"))],
)
def get_member_detail(member_id: int, db: MembersSessionDep) -> MemberDetailSchema:
    member = get_member(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member with ID {member_id} not found.")
    return _detail(db, member)


@router.post(
    "",
    name="create_member",
    description="Create a member",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("members", "create")),
        Depends(rate_limit("20/minute", scope="create_member")),
    ],
)
def post_member(body: MemberCreateSchema, db: MembersSessionDep) -> MemberDetailSchema:
    try:
        member = create_member(
            db,
            name=body.name,
            email=body.email,
            phone=body.phone,
            address=body.address,
            birth_date=body.birth_date,
            sex=body.sex,
        )
    except DuplicateMemberEmailError as exc:
        raise HTTPException(status_code=409, detail="A member with this email already exists.") from exc
    return _detail(db, member)


@router.patch(
    "/{member_id}",
    name="update_member",
    description="Update the given fields of a member",
    dependencies=[
        Depends(require_permission("members", "update", "all")),
        Depends(rate_limit("30/minute", scope="update_member")),
    ],
)
def patch_member(member_id: int, body: MemberUpdateSchema, db: MembersSessionDep) -> MemberDetailSchema:
    member = get_member(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member with ID {member_id} not found.")
    changes = body.model_dump(exclude_unset=True)
    # name is NOT NULL: an explicit null would otherwise surface as a DB error (500).
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null.")
    try:
        member = update_member(db, member, changes)
    except DuplicateMemberEmailError as exc:
        raise HTTPException(status_code=409, detail="A member with this email already exists.") from exc
    return _detail(db, member)


@router.put(
    "/{member_id}/user",
    name="link_member_user",
    description="Link the member to a user account (members: link)",
    dependencies=[
        Depends(require_permission("members", "link")),
        Depends(rate_limit("20/minute", scope="link_member_user")),
    ],
)
def put_member_user(member_id: int, body: MemberUserLinkSchema, db: MembersSessionDep) -> MemberDetailSchema:
    member = get_member(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member with ID {member_id} not found.")
    try:
        member = link_member_user(db, member, body.user_id)
    except MemberAlreadyLinkedError as exc:
        raise HTTPException(status_code=409, detail="This member is already linked to another user.") from exc
    except UserAlreadyLinkedError as exc:
        raise HTTPException(status_code=409, detail="This user is already linked to another member.") from exc
    return _detail(db, member)


@router.delete(
    "/{member_id}/user",
    name="unlink_member_user",
    description="Remove the member's user link (members: link)",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_permission("members", "link")),
        Depends(rate_limit("20/minute", scope="unlink_member_user")),
    ],
)
def delete_member_user(member_id: int, db: MembersSessionDep) -> None:
    member = get_member(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member with ID {member_id} not found.")
    unlink_member_user(db, member)
