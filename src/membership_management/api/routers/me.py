from fastapi import APIRouter, Depends

from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep, get_current_claims
from membership_management.api.rate_limit import default_user_rate_limit
from membership_management.api.schemas.me import MeLeadSchema, MeMemberSchema, MeSchema
from membership_management.data.members.services import get_member_leads

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
