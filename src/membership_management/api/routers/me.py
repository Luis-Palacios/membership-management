from fastapi import APIRouter, Depends, HTTPException

from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep, get_current_claims, require_permission
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.routers.members import member_detail
from membership_management.api.schemas.me import MeLeadSchema, MeMemberSchema, MeSchema
from membership_management.api.schemas.members import MemberDetailSchema, MyMemberUpdateSchema
from membership_management.data.members.services import get_member_leads, update_member

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


@router.get("", name="get_me", description="Signed-in user, their member (if linked) and groups led")
def get_me(claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep) -> MeSchema:
    if member is None:
        return MeSchema(user_id=claims.sub, role=claims.role, member=None, leads=[])
    return MeSchema(
        user_id=claims.sub,
        role=claims.role,
        member=MeMemberSchema(id=member.id, name=member.name),
        leads=[
            MeLeadSchema(small_group_id=lead.small_group_id, name=lead.small_group_name, role=lead.role)
            for lead in get_member_leads(db, member.id)
        ],
    )


@router.patch(
    "/member",
    name="update_my_member",
    description="Update the given fields of the caller's own member (name, phone, address, birthDate, sex)",
    dependencies=[
        Depends(require_permission("ownProfile", "update")),
        Depends(rate_limit("30/minute", scope="update_my_member")),
    ],
)
def patch_my_member(
    body: MyMemberUpdateSchema, member: CurrentMemberDep, db: MembersSessionDep
) -> MemberDetailSchema:
    # Only the member linked to the JWT `sub`, never an id from the request, so no members scope (rule 2).
    if member is None:
        raise HTTPException(status_code=404, detail="Your account isn't linked to a member.")
    # No email field, so no duplicate-email case to handle.
    return member_detail(db, update_member(db, member, body.model_dump(exclude_unset=True)))
