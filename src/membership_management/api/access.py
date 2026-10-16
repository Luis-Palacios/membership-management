from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException

from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import AuthClaims, CurrentClaimsDep, has_permission
from membership_management.data.small_groups.models import SmallGroupRole
from membership_management.data.small_groups.services import get_active_membership, get_led_small_group_ids


@dataclass(frozen=True)
class SmallGroupScope:
    """Which small groups the caller may touch: all of them (`full`) or just `group_ids`.

    `full` is `smallGroups: all`; without it the scope is the groups the caller's member leads, or
    co-led when they closed. Permissions say what the caller may do, this says on which groups.
    """

    full: bool
    group_ids: frozenset[int]
    member_id: int | None

    def includes(self, small_group_id: int) -> bool:
        return self.full or small_group_id in self.group_ids


def get_small_group_scope(
    claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep
) -> SmallGroupScope:
    """403 without `smallGroups: view`: leading a group grants nothing by itself."""
    if not has_permission(claims, "smallGroups", "view"):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    member_id = member.id if member is not None else None
    if has_permission(claims, "smallGroups", "all"):
        return SmallGroupScope(full=True, group_ids=frozenset(), member_id=member_id)
    group_ids = get_led_small_group_ids(db, member_id) if member_id is not None else frozenset()
    return SmallGroupScope(full=False, group_ids=group_ids, member_id=member_id)


SmallGroupScopeDep = Annotated[SmallGroupScope, Depends(get_small_group_scope)]


_OWN_ROW = "Ask an admin or elder to change your own role in this group."
_LEADERSHIP = "Only admins and elders can change who leads a group."


def _can_set_leader(claims: AuthClaims) -> bool:
    return has_permission(claims, "smallGroups", "setLeader")


def ensure_caller_can_add_member(claims: AuthClaims, role: SmallGroupRole) -> None:
    """Rule 9: adding a leader needs `smallGroups: setLeader`."""
    if role == SmallGroupRole.LEADER and not _can_set_leader(claims):
        raise HTTPException(status_code=403, detail=_LEADERSHIP)


def ensure_caller_can_change_member(
    db: MembersSessionDep,
    claims: AuthClaims,
    scope: SmallGroupScope,
    small_group_id: int,
    member_id: int,
    new_role: SmallGroupRole | None,
) -> None:
    """Rule 9 for change/remove (`new_role=None` means remove).

    Without `smallGroups: all`, not your own row. Without `smallGroups: setLeader`, never to or from
    leader. Order: own row, then leadership. A target with no active membership passes so the
    service answers 404.
    """
    if not scope.full and member_id == scope.member_id:
        raise HTTPException(status_code=403, detail=_OWN_ROW)
    if _can_set_leader(claims):
        return
    if new_role == SmallGroupRole.LEADER:
        raise HTTPException(status_code=403, detail=_LEADERSHIP)
    target = get_active_membership(db, small_group_id, member_id)
    if target is not None and target.role == SmallGroupRole.LEADER:
        raise HTTPException(status_code=403, detail=_LEADERSHIP)
