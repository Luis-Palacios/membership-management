"""Small group reports' side of the report submitted emails (report-submitted-emails spec, *Contracts →
membership-management*): the event a submit writes. Mirrors `conversation_notifications.py`.
"""

from datetime import datetime

from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.conversation_notifications import EMAIL_DEADLINE, HEAD_START
from membership_management.data.small_groups.models import SmallGroupReport

REPORT_SUBMITTED = "small_group_report.submitted"


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
