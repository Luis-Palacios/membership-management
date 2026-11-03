from datetime import datetime, time, timedelta

from sqlalchemy import func, select

from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.seed.small_group_reports import CHURCH_WIDE_REASON, church_wide_week_start
from membership_management.data.small_groups.models import (
    ReportConversationComment,
    SmallGroup,
    SmallGroupNoMeetingWeek,
    SmallGroupReport,
)
from membership_management.data.small_groups.queries import reported_group_ids_in_week_query


def seed_no_meeting_week(ctx: SeedContext) -> None:
    """Mark `church_wide_week_start` church-wide, as `mark_no_meeting_week` does (without its commit):
    every open group with a meeting day and no report in the week gets a linked no meeting."""
    session = ctx.session
    week_start = church_wide_week_start(ctx.today)
    week_end = week_start + timedelta(days=6)
    # An elder who comments on reports (`seed_report_conversations`).
    creator_id = session.scalars(
        select(ReportConversationComment.author_member_id)
        .where(ReportConversationComment.side == "elders")
        .order_by(ReportConversationComment.id)
        .limit(1)
    ).one()
    # Marked late, after the week's reports came in, so the leader's own mark was first.
    last_submitted = session.scalar(
        select(func.max(SmallGroupReport.submitted_at)).where(
            SmallGroupReport.meeting_date >= week_start, SmallGroupReport.meeting_date <= week_end
        )
    )
    marked_at = (
        last_submitted + timedelta(hours=1)
        if last_submitted is not None
        else datetime.combine(week_end, time(9, 0), MANAGUA_TZ)
    )
    week = SmallGroupNoMeetingWeek(
        week_start=week_start,
        reason=CHURCH_WIDE_REASON,
        created_by_member_id=creator_id,
        created_at=marked_at,
        updated_at=marked_at,
    )
    session.add(week)
    session.flush()
    groups = list(
        session.scalars(
            select(SmallGroup)
            .where(SmallGroup.closed_at.is_(None), SmallGroup.meeting_day.is_not(None))
            .order_by(SmallGroup.id)
        )
    )
    group_ids = frozenset(g.id for g in groups)
    reported = set(session.scalars(reported_group_ids_in_week_query(group_ids, week_start, week_end)))
    for group in groups:
        if group.id in reported or group.meeting_day is None:
            continue
        session.add(
            SmallGroupReport(
                small_group=group,
                meeting_date=week_start + timedelta(days=group.meeting_day % 7),
                held=False,
                not_held_reason=week.reason,
                submitted_by_member_id=creator_id,
                submitted_at=marked_at,
                no_meeting_week_id=week.id,
            )
        )
    session.flush()
