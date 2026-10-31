from collections.abc import Collection
from datetime import date

from sqlalchemy import ColumnElement, CompoundSelect, Select, and_, case, func, or_, select, union
from sqlalchemy.orm import aliased

from membership_management.data.guests.models import GuestStatusChange
from membership_management.data.members.models import Member, MemberStatusChange
from membership_management.data.small_groups.models import (
    ReportSection,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupReportItem,
    SmallGroupReportItemPerson,
)
from membership_management.data.small_groups.results import PersonKey


def _is_person(
    model: type[SmallGroupReportAttendance] | type[SmallGroupReportItemPerson] | type[SmallGroupMember],
    person: PersonKey,
) -> ColumnElement[bool]:
    """Match a row of `model` that points at `person` (a `member_id` or a `guest_id`, exactly one set)."""
    kind, person_id = person
    return (model.member_id if kind == "member" else model.guest_id) == person_id


def _person_report_ids(person: PersonKey) -> CompoundSelect:
    """Ids of the reports the person has an attendance line in or is tagged in: two index lookups, unioned."""
    on_list = select(SmallGroupReportAttendance.report_id.label("report_id")).where(
        _is_person(SmallGroupReportAttendance, person)
    )
    tagged = (
        select(SmallGroupReportItem.report_id.label("report_id"))
        .join(SmallGroupReportItemPerson, SmallGroupReportItemPerson.item_id == SmallGroupReportItem.id)
        .where(_is_person(SmallGroupReportItemPerson, person))
    )
    return union(on_list, tagged)


def _visible_report(person: PersonKey, observation_groups: frozenset[int] | None) -> ColumnElement[bool]:
    """Reports with something of the person the caller may see (rule 23): an attendance line or any tag
    in the caller's observation audience (`observation_groups`; None: every group), and a prayer or
    praise tag anywhere. The service's `_visible_parts` picks those same parts out of each report."""
    if observation_groups is None:
        return SmallGroupReport.id.in_(_person_report_ids(person))
    tagged_for_anyone = (
        select(SmallGroupReportItem.report_id)
        .join(SmallGroupReportItemPerson, SmallGroupReportItemPerson.item_id == SmallGroupReportItem.id)
        .where(
            _is_person(SmallGroupReportItemPerson, person),
            SmallGroupReportItem.section != ReportSection.FOLLOW_UP,
        )
    )
    return or_(
        and_(
            SmallGroupReport.small_group_id.in_(observation_groups),
            SmallGroupReport.id.in_(_person_report_ids(person)),
        ),
        SmallGroupReport.id.in_(tagged_for_anyone),
    )


def person_timeline_groups_query(person: PersonKey, observation_groups: frozenset[int] | None) -> Select:
    """Each group with a report visible to the caller, any date, and that group's oldest such report."""
    return (
        select(
            SmallGroup.id.label("id"),
            SmallGroup.name.label("name"),
            SmallGroup.audience.label("audience"),
            func.min(SmallGroupReport.meeting_date).label("earliest_date"),
        )
        .join(SmallGroupReport, SmallGroupReport.small_group_id == SmallGroup.id)
        .where(SmallGroupReport.held, _visible_report(person, observation_groups))
        .group_by(SmallGroup.id)
    )


def person_timeline_reports_query(
    person: PersonKey,
    observation_groups: frozenset[int] | None,
    *,
    from_: date | None,
    to: date | None,
    small_group_id: int | None,
    latest: int | None,
) -> Select:
    """Held reports visible to the caller the person has an attendance line in or is tagged in, newest
    first, between `from_` and `to` and in one group when those are given, at most `latest` of them.

    A report has at most one attendance line per person (unique constraint), so the outer join adds no
    rows.
    """
    query = (
        select(
            SmallGroupReport.id.label("report_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            SmallGroup.id.label("small_group_id"),
            SmallGroup.name.label("small_group_name"),
            SmallGroup.audience.label("small_group_audience"),
            SmallGroupReportAttendance.attended_group.label("attended_group"),
            SmallGroupReportAttendance.attended_church.label("attended_church"),
            SmallGroupReportAttendance.observation.label("observation"),
            Member.id.label("submitted_by_member_id"),
            Member.name.label("submitted_by_name"),
        )
        .where(_visible_report(person, observation_groups))
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        .join(Member, Member.id == SmallGroupReport.submitted_by_member_id)
        .outerjoin(
            SmallGroupReportAttendance,
            and_(
                SmallGroupReportAttendance.report_id == SmallGroupReport.id,
                _is_person(SmallGroupReportAttendance, person),
            ),
        )
        .where(SmallGroupReport.held)
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroupReport.id.desc())
        .limit(latest)
    )
    if from_ is not None:
        query = query.where(SmallGroupReport.meeting_date >= from_)
    if to is not None:
        query = query.where(SmallGroupReport.meeting_date <= to)
    if small_group_id is not None:
        query = query.where(SmallGroupReport.small_group_id == small_group_id)
    return query


def person_timeline_periods_query(person: PersonKey) -> Select:
    """All the person's membership periods, to find their role in a group on a meeting date."""
    return select(
        SmallGroupMember.small_group_id.label("small_group_id"),
        SmallGroupMember.role.label("role"),
        SmallGroupMember.joined_at.label("joined_at"),
        SmallGroupMember.left_at.label("left_at"),
        SmallGroupMember.id.label("period_id"),
    ).where(_is_person(SmallGroupMember, person))


def person_timeline_items_query(person: PersonKey, report_ids: Collection[int]) -> Select:
    """The items of these reports tagging the person, by report, then section (prayer, praise,
    follow-up), then position."""
    section_order = case(
        {"prayer": 0, "praise": 1, "followUp": 2}, value=SmallGroupReportItem.section, else_=3
    )
    return (
        select(
            SmallGroupReportItem.id.label("id"),
            SmallGroupReportItem.report_id.label("report_id"),
            SmallGroupReportItem.section.label("section"),
            SmallGroupReportItem.text.label("text"),
        )
        .join(SmallGroupReportItemPerson, SmallGroupReportItemPerson.item_id == SmallGroupReportItem.id)
        .where(SmallGroupReportItem.report_id.in_(report_ids), _is_person(SmallGroupReportItemPerson, person))
        .order_by(SmallGroupReportItem.report_id, section_order, SmallGroupReportItem.position)
    )


def _status_changes_of(
    person: PersonKey,
) -> tuple[type[MemberStatusChange] | type[GuestStatusChange], ColumnElement[bool]]:
    """The person's status history table, and the condition that keeps their rows."""
    kind, person_id = person
    if kind == "member":
        return MemberStatusChange, MemberStatusChange.member_id == person_id
    return GuestStatusChange, GuestStatusChange.guest_id == person_id


def person_timeline_status_changes_query(
    person: PersonKey, *, from_: date | None, to: date | None, latest: int | None
) -> Select:
    """The person's status changes, newest first, with the member linked to whoever made each (if any),
    between `from_` and `to` when given, at most `latest` of them."""
    model, is_person = _status_changes_of(person)
    changed_by = aliased(Member)
    query = (
        select(
            model.effective_date.label("effective_date"),
            model.status.label("status"),
            model.reason.label("reason"),
            model.note.label("note"),
            changed_by.id.label("changed_by_member_id"),
            changed_by.name.label("changed_by_name"),
        )
        .outerjoin(changed_by, changed_by.user_id == model.changed_by_user_id)
        .where(is_person)
        .order_by(model.effective_date.desc(), model.created_at.desc(), model.id.desc())
        .limit(latest)
    )
    if from_ is not None:
        query = query.where(model.effective_date >= from_)
    if to is not None:
        query = query.where(model.effective_date <= to)
    return query


def person_timeline_earliest_status_change_query(person: PersonKey) -> Select:
    """The date of the person's oldest status change, whatever the range."""
    model, is_person = _status_changes_of(person)
    return select(func.min(model.effective_date)).where(is_person)
