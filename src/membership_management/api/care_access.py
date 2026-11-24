"""What the care log needs to know about the caller: permissions, scopes and the observation audience."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from membership_management.api.access import (
    GuestScope,
    GuestScopeDep,
    MemberScope,
    MemberScopeDep,
    OptionalSmallGroupScopeDep,
    conversation_group_ids,
)
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.jwt_auth import AuthClaims, CurrentClaimsDep, has_permission
from membership_management.data.care.access_rules import CareLogViewer
from membership_management.data.members.models import Member
from membership_management.data.small_groups.access_rules import SmallGroupScope


@dataclass(frozen=True)
class CareContext:
    """The caller as the care log sees them: who they are, who they may see, which groups' observations
    they read (for the links to reports, items and threads)."""

    claims: AuthClaims
    member: Member | None
    viewer: CareLogViewer
    member_scope: MemberScope
    guest_scope: GuestScope
    group_scope: SmallGroupScope | None
    # The groups whose observations the caller reads: None is every group.
    observation_groups: frozenset[int] | None


def care_context(
    claims: AuthClaims,
    member: Member | None,
    member_scope: MemberScope,
    guest_scope: GuestScope,
    group_scope: SmallGroupScope | None,
) -> CareContext:
    viewer = CareLogViewer(
        user_id=claims.sub,
        sees_all=has_permission(claims, "careLog", "all"),
        can_view=has_permission(claims, "careLog", "view"),
        members_full=member_scope.full,
        member_group_ids=member_scope.group_ids,
        guests_full=guest_scope.full,
        guest_group_ids=guest_scope.group_ids,
        member_id=member.id if member is not None else None,
    )
    return CareContext(
        claims=claims,
        member=member,
        viewer=viewer,
        member_scope=member_scope,
        guest_scope=guest_scope,
        group_scope=group_scope,
        observation_groups=conversation_group_ids(claims, group_scope),
    )


def get_care_context(
    claims: CurrentClaimsDep,
    member: CurrentMemberDep,
    member_scope: MemberScopeDep,
    guest_scope: GuestScopeDep,
    group_scope: OptionalSmallGroupScopeDep,
) -> CareContext:
    return care_context(claims, member, member_scope, guest_scope, group_scope)


CareContextDep = Annotated[CareContext, Depends(get_care_context)]
