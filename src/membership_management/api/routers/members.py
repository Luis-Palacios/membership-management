from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from membership_management.api.access import MemberScope, MemberScopeDep
from membership_management.api.church_time import church_today
from membership_management.api.coded_errors import CodedHTTPError
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
from membership_management.api.schemas.members import (
    MemberCreateSchema,
    MemberDeactivateSchema,
    MemberDetailSchema,
    MemberOptionSchema,
    MemberPastSmallGroupSchema,
    MemberReactivateSchema,
    MemberSearchResultSchema,
    MemberSmallGroupSchema,
    MemberStatusChangeSchema,
    MemberSummarySchema,
    MemberUpdateSchema,
    MemberUserLinkSchema,
)
from membership_management.data.members.models import Member, MemberStatus
from membership_management.data.members.services import (
    DuplicateMemberEmailError,
    EffectiveDateInFutureError,
    MemberAlreadyActiveError,
    MemberAlreadyInactiveError,
    MemberAlreadyLinkedError,
    MemberInactiveError,
    MemberLeadsGroupError,
    UserAlreadyLinkedError,
    create_member,
    deactivate_member,
    get_member,
    get_member_latest_status_change,
    get_member_past_small_groups,
    get_member_small_groups,
    get_member_status_history,
    link_member_user,
    list_member_options,
    list_members,
    reactivate_member,
    search_members,
    unlink_member_user,
    update_member,
)

router = APIRouter(
    prefix="/members",
    tags=["members"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


def member_detail(db: MembersSessionDep, member: Member, claims: AuthClaims) -> MemberDetailSchema:
    """The member as `claims` may see them: everyone who can see a member sees that they're inactive and
    since when; the reason and note only go to `members: setStatus` (inactive-members rule 5)."""
    small_groups = get_member_small_groups(db, member.id)
    inactive = member.status == MemberStatus.INACTIVE
    change = get_member_latest_status_change(db, member.id) if inactive else None
    private = change is not None and has_permission(claims, "members", "setStatus")
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
        status=member.status,
        inactive_since=change.effective_date if change is not None else None,
        inactive_reason=change.reason if private and change is not None else None,
        inactive_note=change.note if private and change is not None else None,
        past_small_groups=[
            MemberPastSmallGroupSchema(
                small_group_id=group.small_group_id,
                small_group_name=group.small_group_name,
                role=group.role,
                joined_at=group.joined_at,
                left_at=group.left_at,
            )
            for group in (get_member_past_small_groups(db, member.id) if inactive else [])
        ],
    )


def _get_or_404(db: MembersSessionDep, member_id: int, scope: MemberScope | None = None) -> Member:
    """404 when the member doesn't exist or is outside the scope, with the same message for both."""
    member = get_member(db, member_id) if scope is None or scope.includes(db, member_id) else None
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member with ID {member_id} not found.")
    return member


@router.get(
    "",
    name="list_members",
    description="List members with email and phone; active ones unless status is inactive or all",
    dependencies=[Depends(require_permission("members", "view", "all"))],
)
def get_members(
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    status: Annotated[Literal["active", "inactive", "all"], Query()] = "active",
) -> list[MemberSummarySchema]:
    # The reason is private (rule 5): only for callers who can mark members inactive.
    private = has_permission(claims, "members", "setStatus")
    return [
        MemberSummarySchema(
            id=m.id,
            name=m.name,
            email=m.email,
            phone=m.phone,
            user_id=m.user_id,
            status=m.status,
            inactive_since=m.inactive_since,
            inactive_reason=m.inactive_reason if private else None,
        )
        for m in list_members(db, None if status == "all" else MemberStatus(status))
    ]


# Declared before `/{member_id}` so "options" is never read as a member id.
@router.get(
    "/options",
    name="list_member_options",
    description="Every active member's id and name, by name (the add-member picker)",
    dependencies=[Depends(require_permission("members", "search"))],
)
def get_member_options(db: MembersSessionDep) -> list[MemberOptionSchema]:
    return [MemberOptionSchema(id=m.id, name=m.name) for m in list_member_options(db)]


@router.get(
    "/search",
    name="search_members",
    description="Find members by name within your members scope (the top bar search)",
    dependencies=[Depends(require_permission("members", "view"))],
)
def get_member_search(
    db: MembersSessionDep,
    scope: MemberScopeDep,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[MemberSearchResultSchema]:
    text = q.strip()
    if len(text) < 2:
        return []
    found = search_members(db, text, scope.group_ids, everyone=scope.full, limit=limit)
    return [MemberSearchResultSchema(id=m.id, name=m.name, status=m.status) for m in found]


@router.get(
    "/{member_id}",
    name="get_member",
    description="Get a member with their current small groups (your own, or within your members scope)",
)
def get_membermember_detail(
    member_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    current_member: CurrentMemberDep,
    scope: MemberScopeDep,
) -> MemberDetailSchema:
    # The caller's own member is always readable (rule 11), whatever the role: My profile loads it.
    if current_member is not None and current_member.id == member_id:
        return member_detail(db, current_member, claims)
    if not has_permission(claims, "members", "view"):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return member_detail(db, _get_or_404(db, member_id, scope), claims)


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
def post_member(
    body: MemberCreateSchema, db: MembersSessionDep, claims: CurrentClaimsDep
) -> MemberDetailSchema:
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
    return member_detail(db, member, claims)


@router.patch(
    "/{member_id}",
    name="update_member",
    description="Update the given fields of a member (within the caller's members scope)",
    dependencies=[
        Depends(require_permission("members", "update")),
        Depends(rate_limit("30/minute", scope="update_member")),
    ],
)
def patch_member(
    member_id: int,
    body: MemberUpdateSchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: MemberScopeDep,
) -> MemberDetailSchema:
    member = _get_or_404(db, member_id, scope)
    changes = body.model_dump(exclude_unset=True)
    # Email is what an accepted invite matches to link a member to a user, so without `members: all`
    # it can change only while the member has no user (rule 8). After the scope check: out of scope
    # stays 404.
    if "email" in changes and member.user_id is not None and not has_permission(claims, "members", "all"):
        raise HTTPException(
            status_code=403,
            detail="This member is linked to a user. Ask an admin or elder to change their email.",
        )
    # name is NOT NULL: an explicit null would otherwise surface as a DB error (500).
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="name cannot be null.")
    try:
        member = update_member(db, member, changes)
    except DuplicateMemberEmailError as exc:
        raise HTTPException(status_code=409, detail="A member with this email already exists.") from exc
    return member_detail(db, member, claims)


@router.put(
    "/{member_id}/user",
    name="link_member_user",
    description="Link the member to a user account (members: link)",
    dependencies=[
        Depends(require_permission("members", "link")),
        Depends(rate_limit("20/minute", scope="link_member_user")),
    ],
)
def put_member_user(
    member_id: int, body: MemberUserLinkSchema, db: MembersSessionDep, claims: CurrentClaimsDep
) -> MemberDetailSchema:
    member = _get_or_404(db, member_id)
    try:
        member = link_member_user(db, member, body.user_id)
    except MemberInactiveError as exc:
        raise CodedHTTPError(409, "This member is inactive.", "member_inactive") from exc
    except MemberAlreadyLinkedError as exc:
        raise HTTPException(status_code=409, detail="This member is already linked to another user.") from exc
    except UserAlreadyLinkedError as exc:
        raise HTTPException(status_code=409, detail="This user is already linked to another member.") from exc
    return member_detail(db, member, claims)


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
    member = _get_or_404(db, member_id)
    unlink_member_user(db, member)


@router.post(
    "/{member_id}/deactivate",
    name="deactivate_member",
    description="Mark the member inactive: ends every open group period today (members: setStatus)",
    dependencies=[
        Depends(require_permission("members", "setStatus")),
        Depends(rate_limit("20/minute", scope="deactivate_member")),
    ],
)
def post_member_deactivate(
    member_id: int, body: MemberDeactivateSchema, db: MembersSessionDep, claims: CurrentClaimsDep
) -> MemberDetailSchema:
    member = _get_or_404(db, member_id)
    # Rule 8, before the service: nobody marks their own member inactive.
    if member.user_id == claims.sub:
        raise CodedHTTPError(409, "You can't mark your own member as inactive.", "self")
    try:
        member = deactivate_member(
            db,
            member,
            reason=body.reason,
            effective_date=body.effective_date,
            note=body.note,
            changed_by_user_id=claims.sub,
            today=church_today(),
        )
    except MemberAlreadyInactiveError as exc:
        raise CodedHTTPError(409, "This member is already inactive.", "already_inactive") from exc
    except MemberLeadsGroupError as exc:
        raise CodedHTTPError(
            409,
            "This member leads a small group. Choose another leader first.",
            "leads_group",
            groups=[{"id": g.small_group_id, "name": g.small_group_name} for g in exc.groups],
        ) from exc
    except EffectiveDateInFutureError as exc:
        raise HTTPException(status_code=422, detail="The date they left can't be in the future.") from exc
    return member_detail(db, member, claims)


@router.post(
    "/{member_id}/reactivate",
    name="reactivate_member",
    description="Mark the member active again from today; their groups are not restored (members: setStatus)",
    dependencies=[
        Depends(require_permission("members", "setStatus")),
        Depends(rate_limit("20/minute", scope="reactivate_member")),
    ],
)
def post_member_reactivate(
    member_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    body: MemberReactivateSchema | None = None,
) -> MemberDetailSchema:
    member = _get_or_404(db, member_id)
    try:
        member = reactivate_member(
            db,
            member,
            note=body.note if body is not None else None,
            changed_by_user_id=claims.sub,
            today=church_today(),
        )
    except MemberAlreadyActiveError as exc:
        raise CodedHTTPError(409, "This member is already active.", "already_active") from exc
    return member_detail(db, member, claims)


@router.get(
    "/{member_id}/status-history",
    name="get_member_status_history",
    description="Every status change of the member, newest first (members: setStatus)",
    dependencies=[Depends(require_permission("members", "setStatus"))],
)
def get_member_status_history_route(member_id: int, db: MembersSessionDep) -> list[MemberStatusChangeSchema]:
    member = _get_or_404(db, member_id)
    return [
        MemberStatusChangeSchema(**change._asdict()) for change in get_member_status_history(db, member.id)
    ]
