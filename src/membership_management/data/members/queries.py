from sqlalchemy import ScalarSelect, Select, case, func, select
from sqlalchemy.orm import InstrumentedAttribute, aliased

from membership_management.data.members.models import Member, MemberStatus, MemberStatusChange
from membership_management.data.small_groups.models import (
    LeftReason,
    SmallGroup,
    SmallGroupMember,
    SmallGroupRole,
)
from membership_management.data.small_groups.queries import leads_in_scope_condition


def _latest_status_change_column(column: InstrumentedAttribute) -> ScalarSelect:
    """`column` of the member's latest status change (correlated to `members`)."""
    return (
        select(column)
        .where(MemberStatusChange.member_id == Member.id)
        .order_by(MemberStatusChange.created_at.desc(), MemberStatusChange.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def list_members_query(status: MemberStatus | None = MemberStatus.ACTIVE) -> Select:
    """Members with the given status (`None`: all of them). Inactive ones carry the date they left and why;
    the reason is private, so callers without `members: setStatus` must not pass it on."""
    inactive = Member.status == MemberStatus.INACTIVE
    query = select(
        Member.id.label("id"),
        Member.name.label("name"),
        Member.email.label("email"),
        Member.phone.label("phone"),
        Member.user_id.label("user_id"),
        Member.status.label("status"),
        case((inactive, _latest_status_change_column(MemberStatusChange.effective_date))).label(
            "inactive_since"
        ),
        case((inactive, _latest_status_change_column(MemberStatusChange.reason))).label("inactive_reason"),
    ).order_by(Member.id)
    return query if status is None else query.where(Member.status == status)


def member_options_query() -> Select:
    """Every active member's id and name, by name (the add-member and leader pickers; rule 11)."""
    return (
        select(Member.id.label("id"), Member.name.label("name"))
        .where(Member.status == MemberStatus.ACTIVE)
        .order_by(Member.name, Member.id)
    )


def member_search_query(
    text: str, only_group_ids: frozenset[int] | None, *, everyone: bool, limit: int
) -> Select:
    """Members whose name contains `text` (ignoring case and accents), by name.

    `everyone` is the `members: all` scope. Otherwise only members with an active membership in an
    open group among `only_group_ids` (`None`: any open group), the same scope as
    `member_active_in_open_groups_query`.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = (
        select(Member.id.label("id"), Member.name.label("name"), Member.status.label("status"))
        .where(func.unaccent(Member.name).ilike(func.unaccent(f"%{escaped}%"), escape="\\"))
        .order_by(Member.name, Member.id)
        .limit(limit)
    )
    if everyone:
        return query
    in_scope = (
        select(SmallGroupMember.member_id)
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(SmallGroupMember.left_at.is_(None), SmallGroup.closed_at.is_(None))
    )
    if only_group_ids is not None:
        in_scope = in_scope.where(SmallGroup.id.in_(only_group_ids))
    return query.where(Member.id.in_(in_scope))


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


def member_open_leader_groups_query(member_id: int) -> Select:
    """The open groups the member is the leader of right now (co-leaders don't count; rule 7)."""
    return (
        select(SmallGroup.id.label("small_group_id"), SmallGroup.name.label("small_group_name"))
        .select_from(SmallGroupMember)
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.role == SmallGroupRole.LEADER,
            SmallGroupMember.left_at.is_(None),
            SmallGroup.closed_at.is_(None),
        )
        .order_by(SmallGroup.name)
    )


def member_latest_status_change_query(member_id: int) -> Select:
    return (
        select(MemberStatusChange)
        .where(MemberStatusChange.member_id == member_id)
        .order_by(MemberStatusChange.created_at.desc(), MemberStatusChange.id.desc())
        .limit(1)
    )


def member_status_history_query(member_id: int) -> Select:
    """Every status change of the member, newest first, with the name of whoever made it (when that
    user is linked to a member)."""
    changed_by = aliased(Member)
    return (
        select(
            MemberStatusChange.status.label("status"),
            MemberStatusChange.reason.label("reason"),
            MemberStatusChange.effective_date.label("effective_date"),
            MemberStatusChange.note.label("note"),
            MemberStatusChange.changed_by_user_id.label("changed_by_user_id"),
            changed_by.name.label("changed_by_name"),
            MemberStatusChange.created_at.label("created_at"),
        )
        .outerjoin(changed_by, changed_by.user_id == MemberStatusChange.changed_by_user_id)
        .where(MemberStatusChange.member_id == member_id)
        .order_by(MemberStatusChange.created_at.desc(), MemberStatusChange.id.desc())
    )


def member_past_small_groups_query(member_id: int) -> Select:
    """The periods the member's latest deactivation ended.

    Deactivating closes every open period on the same day, so these are the `member_inactive` periods
    with the latest `left_at`. Reactivating reopens nothing, so while the member is inactive no later
    period can exist.
    """
    latest = (
        select(func.max(SmallGroupMember.left_at))
        .where(
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.left_reason == LeftReason.MEMBER_INACTIVE,
        )
        .scalar_subquery()
    )
    return (
        select(
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroupMember.role.label("role"),
            SmallGroupMember.joined_at.label("joined_at"),
            SmallGroupMember.left_at.label("left_at"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .where(
            SmallGroupMember.member_id == member_id,
            SmallGroupMember.left_reason == LeftReason.MEMBER_INACTIVE,
            SmallGroupMember.left_at == latest,
        )
        .order_by(SmallGroup.name)
    )
