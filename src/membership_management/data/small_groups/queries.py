from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import aliased

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import SmallGroup, SmallGroupMember, SmallGroupRole


def list_small_groups_query() -> Select:
    # The partial unique index allows at most one active leader row per group, so joining it
    # next to the active-member join can't change the count; its columns just join the GROUP BY.
    leader = aliased(SmallGroupMember)
    leader_member = aliased(Member)
    return (
        select(
            SmallGroup.id.label("id"),
            SmallGroup.name.label("name"),
            SmallGroup.meeting_address.label("meeting_address"),
            SmallGroup.meeting_day.label("meeting_day"),
            SmallGroup.closed_at.label("closed_at"),
            func.count(SmallGroupMember.id).label("active_member_count"),
            leader_member.id.label("leader_member_id"),
            leader_member.name.label("leader_name"),
        )
        .outerjoin(
            SmallGroupMember,
            and_(SmallGroupMember.small_group_id == SmallGroup.id, SmallGroupMember.left_at.is_(None)),
        )
        .outerjoin(
            leader,
            and_(
                leader.small_group_id == SmallGroup.id,
                leader.role == SmallGroupRole.LEADER,
                leader.left_at.is_(None),
            ),
        )
        .outerjoin(leader_member, leader_member.id == leader.member_id)
        .group_by(SmallGroup.id, leader_member.id)
        .order_by(SmallGroup.name, SmallGroup.id)
    )


def small_group_active_members_query(small_group_id: int) -> Select:
    """The members currently in the group (open membership periods only)."""
    return (
        select(
            Member.id.label("member_id"),
            Member.name.label("member_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
        )
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(SmallGroupMember.small_group_id == small_group_id, SmallGroupMember.left_at.is_(None))
        .order_by(Member.name, Member.id)
    )
