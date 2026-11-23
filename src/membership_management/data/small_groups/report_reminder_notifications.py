"""Small group reports' side of the weekly report reminder emails (report-reminder-emails spec,
*Contracts → membership-management*): the event the worker's trigger writes once per church week
(`worker/reminder_trigger.py`), and the consumer that turns it into notification requests for the
leaders who still owe a report. Mirrors `report_submitted_notifications.py`; hands its requests to
`notifications/` and never reads channel preferences.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member, MemberStatus
from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.access_rules import Perms, holds
from membership_management.data.small_groups.models import (
    ReportStatus,
    SmallGroup,
    SmallGroupMember,
    SmallGroupNoMeetingWeek,
    SmallGroupReport,
    SmallGroupRole,
)
from membership_management.notifications.deliveries import NotificationRequest, clip_name, create_deliveries

REMINDER_DUE = "small_group_report.reminder_due"
# The notifications/ category: the "Weekly report reminders" switch in My profile.
CATEGORY = "report_reminder"
_TEMPLATE = "report.reminder"
# auth-server's limits on recipientName and the group name (trimmed, 1-200), and on the group list.
_NAME_LIMIT = 200
_MAX_GROUPS = 50


@dataclass(frozen=True)
class _Leading:
    """One open group that still owes this week's report, as led by one person."""

    user_id: str
    member_name: str
    group_id: int
    group_name: str


def _week_start(payload: Mapping[str, Any]) -> date:
    return date.fromisoformat(payload["weekStart"])


def _church_wide_no_meeting(session: Session, week_start: date) -> bool:
    """Rule 7: a church-wide no meeting for the week means nobody is reminded."""
    return bool(
        session.scalar(
            select(exists().where(SmallGroupNoMeetingWeek.week_start == week_start)),
        )
    )


def _leaders_to_remind_query(week_start: date) -> Select:
    """Rules 5, 6 and 9: the active leaders and co-leaders (active member, linked user) of every open
    group with no submitted report, held or not, dated in the church week."""
    week_end = week_start + timedelta(days=6)
    submitted = exists().where(
        SmallGroupReport.small_group_id == SmallGroup.id,
        SmallGroupReport.status == ReportStatus.SUBMITTED,
        SmallGroupReport.meeting_date.between(week_start, week_end),
    )
    return (
        select(Member.user_id, Member.name, SmallGroup.id, SmallGroup.name)
        .select_from(SmallGroupMember)
        .join(SmallGroup, SmallGroup.id == SmallGroupMember.small_group_id)
        .join(Member, Member.id == SmallGroupMember.member_id)
        .where(
            SmallGroup.closed_at.is_(None),
            SmallGroupMember.left_at.is_(None),
            SmallGroupMember.role.in_([SmallGroupRole.LEADER, SmallGroupRole.CO_LEADER]),
            Member.status == MemberStatus.ACTIVE,
            Member.user_id.is_not(None),
            ~submitted,
        )
    )


def _leaders_to_remind(session: Session, week_start: date) -> list[_Leading]:
    return [
        _Leading(user_id=user_id, member_name=member_name, group_id=group_id, group_name=group_name)
        for user_id, member_name, group_id, group_name in session.execute(
            _leaders_to_remind_query(week_start)
        )
    ]


def _latest_draft_ids(session: Session, week_start: date, group_ids: Collection[int]) -> dict[int, int]:
    """Rule 8: per group, the id of its most recent draft dated in the church week (by `meeting_date`
    desc, then `id` desc). Groups with no draft are absent."""
    if not group_ids:
        return {}
    rows = session.execute(
        select(SmallGroupReport.small_group_id, SmallGroupReport.id)
        .where(
            SmallGroupReport.small_group_id.in_(group_ids),
            SmallGroupReport.status == ReportStatus.DRAFT,
            SmallGroupReport.meeting_date.between(week_start, week_start + timedelta(days=6)),
        )
        .order_by(SmallGroupReport.meeting_date.desc(), SmallGroupReport.id.desc())
    )
    latest: dict[int, int] = {}
    for group_id, report_id in rows:
        latest.setdefault(group_id, report_id)  # first row per group is its latest
    return latest


def candidate_user_ids(
    session: Session, payload: Mapping[str, Any], possible_watchers: Collection[str]
) -> frozenset[str]:
    """Everyone this event could email, for the one permissions lookup before its transaction: the
    linked users of the active leaders and co-leaders of open groups with no submitted report this
    week. Empty in a church-wide no-meeting week. `possible_watchers` isn't used: leaders are found
    from the groups, not from permissions."""
    week_start = _week_start(payload)
    if _church_wide_no_meeting(session, week_start):
        return frozenset()
    return frozenset(leading.user_id for leading in _leaders_to_remind(session, week_start))


def _link(groups: Sequence[dict[str, Any]], group_ids: Sequence[int], draft_ids: Mapping[int, int]) -> str:
    """Rule 17: where the email's button goes. `groups` and `group_ids` are in the same order."""
    if len(groups) != 1:
        return "/groups/reports"
    group_id = group_ids[0]
    if groups[0]["hasDraft"]:
        return f"/groups/reports/{draft_ids[group_id]}/edit"
    return f"/groups/reports/new?groupId={group_id}"


def process_report_reminder(
    session: Session,
    event: OutboxEvent,
    perms_by_user: Mapping[str, Perms],
    possible_watchers: Collection[str],
) -> int:
    """The consumer, inside the event's transaction (after its fence): who is reminded of what, handed
    to `notifications/`. `perms_by_user` is the pinned snapshot for this event's candidates; only users
    holding `smallGroups: view` and `smallGroupReports: create` are kept (rule 10). Everything is read
    now, so a report submitted since the trigger is not reminded about. One request per person (rule
    11), with their groups sorted by name then id, expiring with the event (rule 4). Returns the
    deliveries created."""
    week_start = _week_start(event.payload)
    if _church_wide_no_meeting(session, week_start):
        return 0
    leading = [
        item
        for item in _leaders_to_remind(session, week_start)
        if (perms := perms_by_user.get(item.user_id)) is not None
        and holds(perms, "smallGroups", "view")
        and holds(perms, "smallGroupReports", "create")
    ]
    if not leading:
        return 0
    draft_ids = _latest_draft_ids(session, week_start, {item.group_id for item in leading})

    by_user: dict[str, dict[int, _Leading]] = defaultdict(dict)
    for item in leading:
        by_user[item.user_id][item.group_id] = item
    requests = []
    for user_id, groups_by_id in sorted(by_user.items()):
        # Rule 11: by group name (case-insensitive, like the groups list), then id.
        ordered = sorted(groups_by_id.values(), key=lambda item: (item.group_name.casefold(), item.group_id))
        ordered = ordered[:_MAX_GROUPS]
        # Rule 16: names and whether a draft exists, no report content.
        groups = [
            {"name": clip_name(item.group_name, _NAME_LIMIT), "hasDraft": item.group_id in draft_ids}
            for item in ordered
        ]
        data = {
            "recipientName": clip_name(ordered[0].member_name, _NAME_LIMIT),
            "groups": groups,
            "weekStart": week_start.isoformat(),
        }
        path = _link(groups, [item.group_id for item in ordered], draft_ids)
        requests.append(
            NotificationRequest(
                recipient_user_id=user_id,
                category=CATEGORY,
                channel="email",
                template=_TEMPLATE,
                payload={"recipientUserId": user_id, "template": _TEMPLATE, "data": data, "path": path},
                not_after=event.expires_at,
            )
        )
    return create_deliveries(session, event.id, requests)
