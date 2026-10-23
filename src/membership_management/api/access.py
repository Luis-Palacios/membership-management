from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from membership_management.api.config import api_settings
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import AuthClaims, CurrentClaimsDep, has_permission
from membership_management.data.guests.lookup_services import get_led_open_guest_group_ids, is_guest_in_groups
from membership_management.data.members.models import Member
from membership_management.data.members.services import is_member_active_in_open_groups
from membership_management.data.small_groups.models import ConversationSide, SmallGroupReport, SmallGroupRole
from membership_management.data.small_groups.services import (
    get_active_membership,
    get_led_small_group_ids,
    observations_visible_to,
)


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


def _small_group_scope(claims: AuthClaims, member: Member | None, db: Session) -> SmallGroupScope | None:
    """None without `smallGroups: view`: leading a group grants nothing by itself."""
    if not has_permission(claims, "smallGroups", "view"):
        return None
    member_id = member.id if member is not None else None
    if has_permission(claims, "smallGroups", "all"):
        return SmallGroupScope(full=True, group_ids=frozenset(), member_id=member_id)
    group_ids = get_led_small_group_ids(db, member_id) if member_id is not None else frozenset()
    return SmallGroupScope(full=False, group_ids=group_ids, member_id=member_id)


def get_small_group_scope(
    claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep
) -> SmallGroupScope:
    """The caller's small group scope; 403 without `smallGroups: view`."""
    scope = _small_group_scope(claims, member, db)
    if scope is None:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return scope


SmallGroupScopeDep = Annotated[SmallGroupScope, Depends(get_small_group_scope)]


def get_optional_small_group_scope(
    claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep
) -> SmallGroupScope | None:
    """Like `get_small_group_scope`, but None instead of 403 for callers outside the small group routes."""
    return _small_group_scope(claims, member, db)


OptionalSmallGroupScopeDep = Annotated[SmallGroupScope | None, Depends(get_optional_small_group_scope)]


@dataclass(frozen=True)
class MemberScope:
    """Which members the caller may see and edit (rule 3).

    `full` is `members: all`. Without it: members with an active membership in an open group of
    the caller's small group scope, `group_ids` (`None` when that scope is every group; empty
    without `smallGroups: view`). Former members and members of closed groups are out.
    """

    full: bool
    group_ids: frozenset[int] | None

    def includes(self, db: Session, member_id: int) -> bool:
        return self.full or is_member_active_in_open_groups(db, member_id, self.group_ids)


def get_member_scope(
    claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep
) -> MemberScope:
    if has_permission(claims, "members", "all"):
        return MemberScope(full=True, group_ids=None)
    group_scope = _small_group_scope(claims, member, db)
    if group_scope is None:
        return MemberScope(full=False, group_ids=frozenset())
    return MemberScope(full=False, group_ids=None if group_scope.full else group_scope.group_ids)


MemberScopeDep = Annotated[MemberScope, Depends(get_member_scope)]


@dataclass(frozen=True)
class GuestScope:
    """Which guests the caller may see and edit (guest-small-groups rule 17).

    `full` is `guests: all`. Otherwise: guests with an open period in an open guest group the caller
    leads or co-leads today (`group_ids`; computed for everyone with a linked member, since it also
    says which groups' observations a caller leads). Leading only member groups, or a guest group that
    has closed, gives nothing. Permissions say what the caller may do, this says on which guests.
    """

    full: bool
    group_ids: frozenset[int]

    def includes(self, db: Session, guest_id: int) -> bool:
        return self.full or is_guest_in_groups(db, guest_id, self.group_ids)

    @property
    def can_search(self) -> bool:
        """Search is church-wide but only for who leads at least one open guest group (or has `all`)."""
        return self.full or bool(self.group_ids)


def get_guest_scope(claims: CurrentClaimsDep, member: CurrentMemberDep, db: MembersSessionDep) -> GuestScope:
    group_ids = get_led_open_guest_group_ids(db, member.id) if member is not None else frozenset()
    return GuestScope(full=has_permission(claims, "guests", "all"), group_ids=group_ids)


GuestScopeDep = Annotated[GuestScope, Depends(get_guest_scope)]


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


def sees_all_observations(claims: AuthClaims) -> bool:
    return has_permission(claims, "smallGroupReports", "viewObservations")


def leads_group(scope: SmallGroupScope, small_group_id: int) -> bool:
    """Reports are only fetched inside the scope, so a non-full caller here leads (or led) the group."""
    return scope.includes(small_group_id)


def comment_side(claims: AuthClaims) -> ConversationSide:
    """Rule 6: `elders` with `smallGroups: all`, else `leaders`. Stored on the comment when written."""
    return "elders" if has_permission(claims, "smallGroups", "all") else "leaders"


def conversation_access(report: SmallGroupReport, claims: AuthClaims, scope: SmallGroupScope) -> None:
    """Rule 3: the audience of the report's observations. 404 outside the scope, 403 outside the audience."""
    if not scope.includes(report.small_group_id):
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report.id} not found.")
    # A full scope is not "leading the group": it needs `viewObservations`, as in `conversation_group_ids`.
    if not observations_visible_to(
        sees_all_observations=sees_all_observations(claims),
        leads_group=not scope.full and leads_group(scope, report.small_group_id),
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")


def conversation_group_ids(claims: AuthClaims, scope: SmallGroupScope | None) -> frozenset[int] | None:
    """The groups whose conversations the caller may see: None = every group, else exactly these ids.

    The same audience as `conversation_access`, for lists: a full scope needs `viewObservations`
    (without it, no group), a scoped caller gets the groups they lead (or led when it closed).
    """
    if scope is None or not has_permission(claims, "smallGroupReports", "view"):
        return frozenset()
    if scope.full:
        return None if sees_all_observations(claims) else frozenset()
    return scope.group_ids


def ensure_guest_groups_enabled() -> None:
    """Rule 1: creating a guest group or a guest is 409 while the setting is off. Reading is never blocked."""
    if not api_settings.guest_groups_enabled:
        raise HTTPException(
            status_code=409, detail="Guests can't be created while guest groups are off for this church."
        )
