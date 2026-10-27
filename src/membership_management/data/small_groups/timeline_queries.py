from sqlalchemy import ColumnElement, CompoundSelect, Select, and_, case, select, union

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
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


def person_timeline_reports_query(person: PersonKey) -> Select:
    """Held reports, any date and group, the person has an attendance line in or is tagged in.

    A report has at most one attendance line per person (unique constraint), so the outer join adds no
    rows. Visibility (rule 23) depends on the caller and is applied by the service.
    """
    return (
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
        .where(SmallGroupReport.id.in_(_person_report_ids(person)))
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
    )


def person_timeline_periods_query(person: PersonKey) -> Select:
    """All the person's membership periods, to find their role in a group on a meeting date."""
    return select(
        SmallGroupMember.small_group_id.label("small_group_id"),
        SmallGroupMember.role.label("role"),
        SmallGroupMember.joined_at.label("joined_at"),
        SmallGroupMember.left_at.label("left_at"),
        SmallGroupMember.id.label("period_id"),
    ).where(_is_person(SmallGroupMember, person))


def person_timeline_items_query(person: PersonKey) -> Select:
    """The items tagging the person, by report, then section (prayer, praise, follow-up), then position."""
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
        .join(SmallGroupReport, SmallGroupReport.id == SmallGroupReportItem.report_id)
        .where(SmallGroupReport.held, _is_person(SmallGroupReportItemPerson, person))
        .order_by(SmallGroupReportItem.report_id, section_order, SmallGroupReportItem.position)
    )
