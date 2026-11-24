from collections.abc import Collection
from datetime import date, timedelta

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    exists,
    false,
    literal,
    null,
    or_,
    select,
    true,
)
from sqlalchemy.orm import InstrumentedAttribute

from membership_management.data.care.access_rules import CareLogViewer
from membership_management.data.care.models import (
    CareLogEntry,
    CareLogEntryParticipant,
    CareLogEntryPerson,
    CareLogStatus,
    CareLogVisibility,
)
from membership_management.data.guests.models import Guest, GuestStatus
from membership_management.data.guests.queries import guest_name_match
from membership_management.data.members.models import Member, MemberStatus
from membership_management.data.members.queries import member_name_match
from membership_management.data.small_groups.models import (
    ReportConversation,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportItem,
)


def member_in_scope_condition(
    viewer: CareLogViewer, member_id: InstrumentedAttribute[int | None] | InstrumentedAttribute[int]
) -> ColumnElement[bool]:
    """The member is in the caller's members scope: `members: all`, or active in an open group of the
    scope (`MemberScope`, `api/access.py`)."""
    if viewer.members_full:
        return true()
    if viewer.member_group_ids is not None and not viewer.member_group_ids:
        return false()
    open_groups = select(SmallGroup.id).where(SmallGroup.closed_at.is_(None))
    if viewer.member_group_ids is not None:
        open_groups = open_groups.where(SmallGroup.id.in_(viewer.member_group_ids))
    return exists().where(
        SmallGroupMember.member_id == member_id,
        SmallGroupMember.left_at.is_(None),
        SmallGroupMember.small_group_id.in_(open_groups),
    )


def guest_in_scope_condition(
    viewer: CareLogViewer, guest_id: InstrumentedAttribute[int | None] | InstrumentedAttribute[int]
) -> ColumnElement[bool]:
    """The guest is in the caller's guests scope: `guests: all`, or with an open period in a guest group
    the caller leads (`GuestScope`, `api/access.py`)."""
    if viewer.guests_full:
        return true()
    if not viewer.guest_group_ids:
        return false()
    return exists().where(
        SmallGroupMember.guest_id == guest_id,
        SmallGroupMember.left_at.is_(None),
        SmallGroupMember.small_group_id.in_(viewer.guest_group_ids),
    )


def care_log_visible_condition(viewer: CareLogViewer) -> ColumnElement[bool]:
    """Rule 8, over `care_log_entries` (deleted entries are the caller's to filter): `careLog: all` sees
    every entry, the author their own, and `careLog: view` the `leaders` entries with at least one of their
    people in the caller's members or guests scope. The one definition; lists, the timeline and the
    single-entry check all use it."""
    if viewer.sees_all:
        return true()
    own = CareLogEntry.author_user_id == viewer.user_id
    if not viewer.can_view:
        return own
    person_in_scope = exists().where(
        CareLogEntryPerson.entry_id == CareLogEntry.id,
        or_(
            and_(
                CareLogEntryPerson.member_id.is_not(None),
                member_in_scope_condition(viewer, CareLogEntryPerson.member_id),
            ),
            and_(
                CareLogEntryPerson.guest_id.is_not(None),
                guest_in_scope_condition(viewer, CareLogEntryPerson.guest_id),
            ),
        ),
    )
    return or_(own, and_(CareLogEntry.visibility == CareLogVisibility.LEADERS, person_in_scope))


def care_log_entry_visible_query(viewer: CareLogViewer, entry_id: int) -> Select:
    """One row when the entry exists, isn't deleted and the caller sees it."""
    return select(CareLogEntry.id).where(
        CareLogEntry.id == entry_id, CareLogEntry.deleted_at.is_(None), care_log_visible_condition(viewer)
    )


def care_people_search_query(viewer: CareLogViewer, text: str, *, limit: int) -> Select:
    """Active members and guests the caller may log care about whose name contains `text` (ignoring case
    and accents). `careLog: all` searches everyone; otherwise the members and guests scopes apply. Ranked:
    names starting with `text`, then the rest, then by name."""
    members = select(
        literal("member").label("kind"),
        Member.id.label("id"),
        Member.name.label("name"),
        null().label("phone"),
        member_name_match(text, prefix=True).label("starts_with"),
    ).where(
        Member.status == MemberStatus.ACTIVE,
        member_name_match(text),
        true() if viewer.sees_all else member_in_scope_condition(viewer, Member.id),
    )
    guests = select(
        literal("guest").label("kind"),
        Guest.id.label("id"),
        Guest.name.label("name"),
        Guest.phone.label("phone"),
        guest_name_match(text, prefix=True).label("starts_with"),
    ).where(
        Guest.status == GuestStatus.ACTIVE,
        guest_name_match(text),
        true() if viewer.sees_all else guest_in_scope_condition(viewer, Guest.id),
    )
    people = members.union_all(guests).subquery()
    return (
        select(people.c.kind, people.c.id, people.c.name, people.c.phone)
        .order_by(people.c.starts_with.desc(), people.c.name, people.c.kind, people.c.id)
        .limit(limit)
    )


def loggable_members_query(viewer: CareLogViewer, member_ids: Collection[int]) -> Select:
    """The ids among `member_ids` of members the caller may log care about (`careLog: all`, or in the
    members scope). Whether they are active is the service's to say, after this."""
    return select(Member.id).where(
        Member.id.in_(member_ids),
        true() if viewer.sees_all else member_in_scope_condition(viewer, Member.id),
    )


def loggable_guests_query(viewer: CareLogViewer, guest_ids: Collection[int]) -> Select:
    """The ids among `guest_ids` of guests the caller may log care about (`careLog: all`, or in the
    guests scope)."""
    return select(Guest.id).where(
        Guest.id.in_(guest_ids),
        true() if viewer.sees_all else guest_in_scope_condition(viewer, Guest.id),
    )


def existing_members_query(member_ids: Collection[int]) -> Select:
    """The ids of the members that exist, for validating participants."""
    return select(Member.id).where(Member.id.in_(member_ids))


def coming_up_query(
    viewer: CareLogViewer, member_id: int | None, *, today: date, horizon_days: int
) -> Select:
    """The caller's planned entries (as author or participant, and that they see) not past `horizon_days`
    from today, soonest first; the past-due ones (before today) are the first rows."""
    mine = CareLogEntry.author_user_id == viewer.user_id
    if member_id is not None:
        mine = or_(
            mine,
            exists().where(
                CareLogEntryParticipant.entry_id == CareLogEntry.id,
                CareLogEntryParticipant.member_id == member_id,
            ),
        )
    return (
        select(CareLogEntry.id)
        .where(
            CareLogEntry.deleted_at.is_(None),
            CareLogEntry.status == CareLogStatus.PLANNED,
            CareLogEntry.occurred_on <= today + timedelta(days=horizon_days),
            mine,
            care_log_visible_condition(viewer),
        )
        .order_by(CareLogEntry.occurred_on, CareLogEntry.occurred_at_time.asc().nulls_last(), CareLogEntry.id)
    )


def source_reports_query(report_ids: Collection[int]) -> Select:
    """Report facts a source link shows, by report id."""
    return (
        select(
            SmallGroupReport.id.label("report_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            SmallGroup.id.label("group_id"),
            SmallGroup.name.label("group_name"),
            SmallGroup.audience.label("group_audience"),
            SmallGroupReport.status.label("report_status"),
        )
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .where(SmallGroupReport.id.in_(report_ids))
    )


def source_items_query(item_ids: Collection[int]) -> Select:
    """Report items by id, with their section and report."""
    return select(
        SmallGroupReportItem.id.label("id"),
        SmallGroupReportItem.report_id.label("report_id"),
        SmallGroupReportItem.section.label("section"),
    ).where(SmallGroupReportItem.id.in_(item_ids))


def source_conversations_query(conversation_ids: Collection[int]) -> Select:
    """Report conversations by id, with their report."""
    return select(ReportConversation.id.label("id"), ReportConversation.report_id.label("report_id")).where(
        ReportConversation.id.in_(conversation_ids)
    )
