"""Small group reports' side of the report submitted emails (report-submitted-emails spec, *Contracts →
membership-management*): the event a submit writes, and the consumer that turns it into notification
requests for the group's watchers. Mirrors `conversation_notifications.py`, whose watcher and reader
rules it reuses; hands its requests to `notifications/` and never reads channel preferences.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.access_rules import Perms
from membership_management.data.small_groups.conversation_notifications import (
    EMAIL_DEADLINE,
    HEAD_START,
    readers_of_group,
)
from membership_management.data.small_groups.conversation_queries import watch_opt_out_user_ids_query
from membership_management.data.small_groups.models import ReportStatus, SmallGroupReport
from membership_management.notifications.config import notification_settings
from membership_management.notifications.deliveries import NotificationRequest, clip_name, create_deliveries
from membership_management.notifications.entries import EntryRequest, create_entries

REPORT_SUBMITTED = "small_group_report.submitted"
# The notifications/ category: the "Submitted reports" switch in My profile.
CATEGORY = "report_submitted"
_TEMPLATE = "report.submitted"
# auth-server's limit on submitterName and groupName (trimmed, 1-200).
_NAME_LIMIT = 200


def report_submitted_event(report: SmallGroupReport, submitted_at: datetime) -> OutboxEvent:
    """The outbox row for a report that just became submitted (payload v1): ids and facts only, never
    the report's text. `submitted_at` is the report's own (read back after the flush, since the column
    is set to `now()`), so the 24 h deadline counts from the submit."""
    if report.submitted_by_member_id is None:
        raise ValueError("a submitted report has a submitter")
    return OutboxEvent(
        event_type=REPORT_SUBMITTED,
        schema_version=1,
        aggregate_type="small_group_report",
        aggregate_id=report.id,
        payload={
            "reportId": report.id,
            "smallGroupId": report.small_group_id,
            "submittedByMemberId": report.submitted_by_member_id,
            "occurredAt": submitted_at.isoformat(),
        },
        created_at=submitted_at,
        next_attempt_at=submitted_at + HEAD_START,
        expires_at=submitted_at + EMAIL_DEADLINE,
    )


def _submitted_report(session: Session, payload: Mapping[str, Any]) -> SmallGroupReport | None:
    """The event's report, while it still exists and is submitted (deleted before processing → None)."""
    report = session.get(SmallGroupReport, payload["reportId"])
    if report is None or report.status != ReportStatus.SUBMITTED or report.submitted_by is None:
        return None
    return report


def _submitter_user_id(report: SmallGroupReport) -> str | None:
    """Rule 6: the submitter is the user linked to `submitted_by_member_id` (None if not linked)."""
    return report.submitted_by.user_id if report.submitted_by is not None else None


def candidate_user_ids(
    session: Session, payload: Mapping[str, Any], possible_watchers: Collection[str]
) -> frozenset[str]:
    """Everyone this event could email, for the one permissions lookup before its transaction: the
    possible watchers minus the submitter's user. Empty when the report is gone or not submitted."""
    report = _submitted_report(session, payload)
    if report is None:
        return frozenset()
    return frozenset(possible_watchers) - {_submitter_user_id(report)}


def choose_recipients(
    *,
    watchers: Collection[str],
    submitter_user_id: str | None,
    opted_out: Collection[str],
    readers: Collection[str],
) -> frozenset[str]:
    """Who hears about a submitted report (rules 5-7): its group's watchers who may read the group's
    conversations (rule 23's check), minus those who unwatched it, never the submitter. Leaders aren't
    possible watchers, so they never get here (rule 7)."""
    return frozenset(u for u in watchers if u != submitter_user_id and u not in opted_out and u in readers)


def process_report_submitted(
    session: Session,
    event: OutboxEvent,
    perms_by_user: Mapping[str, Perms],
    possible_watchers: Collection[str],
) -> int:
    """The consumer, inside the event's transaction (after its fence): who hears about the submitted
    report, and what they're sent, handed to `notifications/`. `perms_by_user` is the pinned snapshot
    for this event's candidates. Names and counts are read now, so a quick edit after submitting shows;
    the delivery's payload never changes after this. A report gone or not submitted gives nothing.
    Returns the deliveries created."""
    report = _submitted_report(session, event.payload)
    if report is None:
        return 0
    group_id = report.small_group_id
    submitter_user_id = _submitter_user_id(report)
    watchers = set(possible_watchers) - {submitter_user_id}
    opted_out = set(session.scalars(watch_opt_out_user_ids_query(group_id, watchers))) if watchers else set()
    chosen = choose_recipients(
        watchers=watchers,
        submitter_user_id=submitter_user_id,
        opted_out=opted_out,
        readers=readers_of_group(session, perms_by_user, group_id),
    )
    if not chosen:
        return 0
    submitter = report.submitted_by
    if submitter is None:  # checked by _submitted_report; for the type checker
        return 0
    # Rule 12: no free text from the report, no member names; only these facts.
    data: dict[str, Any] = {
        "submitterName": clip_name(submitter.name, _NAME_LIMIT),
        "groupName": clip_name(report.small_group.name, _NAME_LIMIT),
        "meetingDate": report.meeting_date.isoformat(),
        "held": report.held,
        "reason": "watcher",
    }
    if report.held:
        # Rule 13: people = attendance rows (members and guests), attended = those with attended_group.
        data["attendedCount"] = sum(1 for a in report.attendances if a.attended_group)
        data["peopleCount"] = len(report.attendances)
    path = f"/groups/reports/{report.id}"
    # The in-app entry (notifications spec, rule 5): the same recipients, before any email preference.
    if (
        notification_settings.in_app_notifications_enabled
        and notification_settings.report_submitted_emails_enabled
    ):
        create_entries(
            session,
            event.id,
            [
                EntryRequest(
                    user_id=user_id,
                    category=CATEGORY,
                    template=_TEMPLATE,
                    data=data,
                    path=path,
                    subject_key=f"small_group_report:{report.id}",
                )
                for user_id in sorted(chosen)
            ],
        )
    requests = [
        NotificationRequest(
            recipient_user_id=user_id,
            category=CATEGORY,
            channel="email",
            template=_TEMPLATE,
            payload={"recipientUserId": user_id, "template": _TEMPLATE, "data": data, "path": path},
            not_after=event.expires_at,
        )
        for user_id in sorted(chosen)
    ]
    return create_deliveries(session, event.id, requests)
