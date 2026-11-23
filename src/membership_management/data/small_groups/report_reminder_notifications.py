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

from sqlalchemy import Select, exists, select, text
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
from membership_management.notifications.config import notification_settings
from membership_management.notifications.deliveries import NotificationRequest, clip_name, create_deliveries
from membership_management.notifications.entries import EntryRequest, EntryResult, create_entries
from membership_management.notifications.push import push_requests

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


def reminder_subject_key(week_start: date) -> str:
    """The `subject_key` of a reminder entry: one per church week (the week's Sunday)."""
    return f"report_reminder:{week_start.isoformat()}"


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
    entries = []
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
        # The in-app entry (notifications spec, rule 5): the same recipients, before any email
        # preference. Every group the person owes, not just the 50 the email names (rule 14 clears it
        # once all of them have submitted).
        entries.append(
            EntryRequest(
                user_id=user_id,
                category=CATEGORY,
                template=_TEMPLATE,
                data=data,
                path=path,
                subject_key=reminder_subject_key(week_start),
                small_group_ids=sorted(groups_by_id),
            )
        )
    stored: dict[str, EntryResult] = {}
    if (
        notification_settings.in_app_notifications_enabled
        and notification_settings.report_reminder_emails_enabled
    ):
        stored = create_entries(session, event.id, entries)
    # Push (rule 5): one more delivery per recipient, same template, data and path.
    if notification_settings.push_enabled_for(notification_settings.report_reminder_emails_enabled):
        requests += push_requests(requests, stored)
    return create_deliveries(session, event.id, requests)


# Rule 14, as one statement: the reminder entries for this church week that name this group and whose
# groups have now ALL got a submitted report dated in the week (the same test as `_leaders_to_remind_query`).
_CLEAR_REMINDERS = text("""
    UPDATE user_notifications n SET read_at = now()
    WHERE n.subject_key = :subject_key
      AND n.read_at IS NULL
      AND :group_id = ANY (n.small_group_ids)
      AND NOT EXISTS (
          SELECT 1 FROM unnest(n.small_group_ids) AS owed(group_id)
          WHERE NOT EXISTS (
              SELECT 1 FROM small_group_reports r
              WHERE r.small_group_id = owed.group_id
                AND r.status = 'submitted'
                AND r.meeting_date BETWEEN :week_start AND :week_end
          )
      )
    RETURNING n.id
""")


# Locks the entries `_CLEAR_REMINDERS` may touch, in id order, before it runs. Without it, two reports
# of the same person's groups submitted at once each see only their own report under READ COMMITTED,
# and the entry is never cleared. With it, the second transaction waits for the first to commit, and its
# next statement (a fresh snapshot) sees both reports.
_LOCK_REMINDERS = text("""
    SELECT n.id FROM user_notifications n
    WHERE n.subject_key = :subject_key
      AND n.read_at IS NULL
      AND :group_id = ANY (n.small_group_ids)
    ORDER BY n.id
    FOR UPDATE
""")


def clear_reminder_entries(session: Session, small_group_id: int, week_start: date) -> int:
    """Rule 14, in the submit transaction: a report for `small_group_id` was just submitted in the church
    week starting `week_start`. Marks read any reminder entry for that week whose groups have now all
    submitted. Flushes first, so the new report counts, and locks the entries first (see
    `_LOCK_REMINDERS`). Doesn't commit. Returns how many were marked."""
    session.flush()
    params = {
        "subject_key": reminder_subject_key(week_start),
        "group_id": small_group_id,
        "week_start": week_start,
        "week_end": week_start + timedelta(days=6),
    }
    locked = session.execute(_LOCK_REMINDERS, {k: params[k] for k in ("subject_key", "group_id")}).all()
    if not locked:
        return 0
    return len(session.execute(_CLEAR_REMINDERS, params).all())
