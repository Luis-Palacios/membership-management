from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException

from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import CurrentClaimsDep
from membership_management.data.small_groups.services import get_led_small_group_ids

# Hand-mirrored role sets (the third copy). Change together with
# auth-server/src/permissions/statements.ts and staff-app/lib/auth/roles.ts.
FULL_ACCESS_ROLES = frozenset({"admin", "elder"})
SCOPED_ROLES = frozenset({"smallGroupLeader", "deacon"})


@dataclass(frozen=True)
class SmallGroupScope:
    """Which small groups the caller may touch: all of them (`full`) or just `group_ids`."""

    full: bool
    group_ids: frozenset[int]
    member_id: int | None

    def includes(self, small_group_id: int) -> bool:
        return self.full or small_group_id in self.group_ids


def get_small_group_scope(
    claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep
) -> SmallGroupScope:
    member_id = member.id if member is not None else None
    if claims.role in FULL_ACCESS_ROLES:
        return SmallGroupScope(full=True, group_ids=frozenset(), member_id=member_id)
    if claims.role in SCOPED_ROLES:
        group_ids = get_led_small_group_ids(db, member_id) if member_id is not None else frozenset()
        return SmallGroupScope(full=False, group_ids=group_ids, member_id=member_id)
    raise HTTPException(status_code=403, detail="You don't have permission to do this.")


SmallGroupScopeDep = Annotated[SmallGroupScope, Depends(get_small_group_scope)]
