from sqlalchemy import Select, select

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import SmallGroup, SmallGroupMember


def list_members_query() -> Select:
    return select(
        Member.id.label("id"),
        Member.name.label("name"),
        Member.email.label("email"),
        Member.phone.label("phone"),
        Member.user_id.label("user_id"),
    ).order_by(Member.id)


def member_active_small_groups_query(member_id: int) -> Select:
    """The groups the member currently belongs to (open membership periods only)."""
    return (
        select(
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.member_id == member_id, SmallGroupMember.left_at.is_(None))
        .order_by(SmallGroup.name)
    )
