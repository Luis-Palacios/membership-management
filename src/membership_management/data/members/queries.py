from sqlalchemy import Select, select

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import SmallGroup, SmallGroupMember
from membership_management.data.small_groups.queries import leads_in_scope_condition


def list_members_query() -> Select:
    return select(
        Member.id.label("id"),
        Member.name.label("name"),
        Member.email.label("email"),
        Member.phone.label("phone"),
        Member.user_id.label("user_id"),
    ).order_by(Member.id)


def member_options_query() -> Select:
    """Every member's id and name, by name (the add-member picker)."""
    return select(Member.id.label("id"), Member.name.label("name")).order_by(Member.name, Member.id)


def member_active_in_open_groups_query(member_id: int, only_group_ids: frozenset[int] | None) -> Select:
    """One row if the member has an active membership in an open group (among `only_group_ids`).

    The members scope of a caller without `members: all`; `None` means any open group.
    """
    query = (
        select(SmallGroupMember.id)
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.left_at.is_(None),
            SmallGroup.closed_at.is_(None),
        )
        .limit(1)
    )
    if only_group_ids is not None:
        query = query.where(SmallGroup.id.in_(only_group_ids))
    return query


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


def member_by_user_id_query(user_id: str) -> Select:
    """The member linked to an auth-server user (`user_id` is unique and indexed)."""
    return select(Member).where(Member.user_id == user_id)


def member_active_leads_query(member_id: int) -> Select:
    """Groups in the member's leader scope, with the period's role.

    Same rule as `led_small_group_ids_query`: leader/co-leader periods that are active or ended by
    the group closing (closed groups included).
    """
    return (
        select(
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroupMember.role.label("role"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.member_id == member_id, leads_in_scope_condition())
        .order_by(SmallGroup.name)
    )
