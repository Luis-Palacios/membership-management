from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from membership_management.data.seed import fixtures
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.seed.report_items import add_report_items
from membership_management.data.small_groups.models import (
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)
from membership_management.data.small_groups.services import church_sunday

if TYPE_CHECKING:
    from membership_management.data.small_groups.results import PersonKey

WEEKS_OF_REPORTS = 8
# Chance a given week has no report (holidays, rain, the leader travelling...). About a third of
# those weeks are recorded as a "no meeting"; the rest stay not filed, so dashboards show all three.
SKIPPED_WEEK_RATE = 0.15
NO_MEETING_SHARE = 1 / 3
ATTENDED_GROUP_RATE = 0.8
ATTENDED_CHURCH_RATE = 0.85
# One past week is marked church-wide (`seed_no_meeting_week`, after every report): the first member
# group's leader marked it first, the other member groups are left empty for the mark, and the guest
# groups (`seed_guests`) met anyway, so the week shows all three.
CHURCH_WIDE_WEEKS_AGO = 2
CHURCH_WIDE_REASON = "Semana Santa: no hay grupos pequeños"


def church_wide_week_start(today: date) -> date:
    return church_sunday(today) - timedelta(weeks=CHURCH_WIDE_WEEKS_AGO)


def seed_small_group_reports(ctx: SeedContext) -> None:
    rng, session = ctx.rng, ctx.session
    current = list(session.scalars(select(SmallGroupMember).where(SmallGroupMember.left_at.is_(None))))
    church_wide = church_wide_week_start(ctx.today)
    for group_index, group in enumerate(session.scalars(select(SmallGroup).order_by(SmallGroup.id))):
        rows = list(
            session.scalars(select(SmallGroupMember).where(SmallGroupMember.small_group_id == group.id))
        )
        # Who a report can tag from another group: members in one today.
        others: list[PersonKey] = sorted(
            {
                ("member", r.member_id)
                for r in current
                if r.small_group_id != group.id and r.member_id is not None
            }
        )
        for meeting_date in _meeting_dates(group, ctx.today):
            skipped = rng.random() < SKIPPED_WEEK_RATE
            no_meeting = skipped and rng.random() < NO_MEETING_SHARE
            if church_sunday(meeting_date) == church_wide:
                # Not the random skips: the first group's leader marks it, the rest wait for the mark.
                if group_index > 0:
                    continue
                no_meeting = True
            elif skipped and not no_meeting:
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
                submitted_by_member_id=submitter.member_id,
                submitted_at=submitted_at,
            )
            add_report_items(
                session,
                report,
                group.name,
                prayer=rng.choice(fixtures.GROUP_PRAYER_REQUESTS),
                praise=rng.choice(fixtures.GROUP_PRAISE_REPORTS) if rng.random() < 0.7 else None,
                follow_up=rng.choice(fixtures.GROUP_DISCUSSIONS) if rng.random() < 0.4 else None,
                roster=[("member", row.member_id) for row in active if row.member_id is not None],
                others=others,
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
