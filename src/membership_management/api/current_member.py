from typing import Annotated

from fastapi import Depends

from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep
from membership_management.data.members.models import Member
from membership_management.data.members.services import get_member_by_user_id


def get_current_member(db: MembersSessionDep, claims: CurrentClaimsDep) -> Member | None:
    """The member behind the verified JWT: the one whose `members.user_id` equals `sub`.

    None is normal (a staff or admin user needn't be a member). The JWT carries no member id; this
    service owns the link, so it is resolved here on every call.
    """
    return get_member_by_user_id(db, claims.sub)


CurrentMemberDep = Annotated[Member | None, Depends(get_current_member)]
