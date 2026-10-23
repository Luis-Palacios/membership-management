from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.seed import fixtures
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.small_groups.models import (
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)

WEEKS_OF_REPORTS = 8
# Chance a given week has no report (holidays, rain, the leader travelling...). About a third of
# those weeks are recorded as a "no meeting"; the rest stay not filed, so dashboards show all three.
SKIPPED_WEEK_RATE = 0.15
NO_MEETING_SHARE = 1 / 3
ATTENDED_GROUP_RATE = 0.8
ATTENDED_CHURCH_RATE = 0.85


def seed_small_group_reports(ctx: SeedContext) -> None:
    rng, session = ctx.rng, ctx.session
    for group in session.scalars(select(SmallGroup).order_by(SmallGroup.id)):
        rows = list(
            session.scalars(select(SmallGroupMember).where(SmallGroupMember.small_group_id == group.id))
        )
        for meeting_date in _meeting_dates(group, ctx.today):
            skipped = rng.random() < SKIPPED_WEEK_RATE
            no_meeting = skipped and rng.random() < NO_MEETING_SHARE
            if skipped and not no_meeting:
                continue
            active = [row for row in rows if _active_on(row, meeting_date)]
            leaders = [row for row in active if row.role != SmallGroupRole.MEMBER]
            if not leaders:
                continue
            # Mostly the leader submits; sometimes the co-leader covers.
            submitter = min(leaders, key=lambda row: row.role != SmallGroupRole.LEADER)
            if len(leaders) > 1 and rng.random() < 0.25:
                submitter = rng.choice(leaders)
            # Filled in that night or within the next day or two, but never in the future.
            submitted_at = min(
                datetime.combine(meeting_date, time(21, 0), MANAGUA_TZ) + timedelta(hours=rng.randint(0, 40)),
                datetime.combine(ctx.today, time(8, 0), MANAGUA_TZ),
            )
            if no_meeting:
                session.add(
                    SmallGroupReport(
                        small_group=group,
                        meeting_date=meeting_date,
                        held=False,
                        not_held_reason=rng.choice(fixtures.NOT_HELD_REASONS),
                        submitted_by_member_id=submitter.member_id,
                        submitted_at=submitted_at,
                    )
                )
                continue
            report = SmallGroupReport(
                small_group=group,
                meeting_date=meeting_date,
                address=group.meeting_address,
                group_prayer_request=rng.choice(fixtures.GROUP_PRAYER_REQUESTS),
                group_praise_report=rng.choice(fixtures.GROUP_PRAISE_REPORTS) if rng.random() < 0.7 else None,
                group_relevant_discussion=(
                    rng.choice(fixtures.GROUP_DISCUSSIONS) if rng.random() < 0.4 else None
                ),
                submitted_by_member_id=submitter.member_id,
                submitted_at=submitted_at,
            )
            for row in active:
                # The submitter was there to fill in the report.
                attended_group = row is submitter or rng.random() < ATTENDED_GROUP_RATE
                report.attendances.append(
                    SmallGroupReportAttendance(
                        member_id=row.member_id,
                        attended_group=attended_group,
                        attended_church=rng.random() < ATTENDED_CHURCH_RATE,
                        observation=(
                            rng.choice(fixtures.ABSENCE_OBSERVATIONS)
                            if not attended_group and rng.random() < 0.5
                            else None
                        ),
                    )
                )
            session.add(report)
    session.flush()


def _meeting_dates(group: SmallGroup, today: date) -> list[date]:
    """The group's last WEEKS_OF_REPORTS meeting days strictly before today, oldest first."""
    if group.meeting_day is None:
        return []
    days_back = (today.isoweekday() - group.meeting_day) % 7 or 7
    latest = today - timedelta(days=days_back)
    return [latest - timedelta(weeks=week) for week in reversed(range(WEEKS_OF_REPORTS))]


def _active_on(row: SmallGroupMember, day: date) -> bool:
    return row.joined_at <= day and (row.left_at is None or row.left_at > day)
