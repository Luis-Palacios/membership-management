from datetime import datetime, time, timedelta

from sqlalchemy import exists, select

from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.small_groups.models import (
    GroupAudience,
    ReportConversation,
    ReportStatus,
    SmallGroup,
    SmallGroupReport,
    SmallGroupReportAttendance,
    SmallGroupRole,
)
from membership_management.data.small_groups.services import NOT_FILED_WINDOW_DAYS, roster_on_date

# Bello Horizonte: attendance taken live, so everyone has the group answer and only some the church one.
LIVE_DRAFT_GROUP = "GP - #4"
LIVE_CHURCH_ANSWERS = 5
# Another group's forgotten report: a few people answered, then nothing.
FORGOTTEN_ANSWERS = 3


def seed_report_drafts(ctx: SeedContext) -> None:
    """Two drafts: `LIVE_DRAFT_GROUP`'s and the first other member group's. Every meeting in the window
    has a report by now, so each takes the date of its group's newest report without conversations, which
    it replaces: the date is then not filed for everyone else, and every seeded thread stays. No random
    numbers, so the other seeders' output doesn't move."""
    groups = ctx.session.scalars(
        select(SmallGroup).where(SmallGroup.audience == GroupAudience.MEMBERS).order_by(SmallGroup.id)
    ).all()
    live = next(g for g in groups if g.name == LIVE_DRAFT_GROUP)
    forgotten = next(g for g in groups if g.name != LIVE_DRAFT_GROUP)
    _replace_with_draft(ctx, live, group_answers=None, church_answers=LIVE_CHURCH_ANSWERS, saves=4)
    _replace_with_draft(
        ctx, forgotten, group_answers=FORGOTTEN_ANSWERS, church_answers=FORGOTTEN_ANSWERS, saves=1
    )
    ctx.session.flush()


def _replace_with_draft(
    ctx: SeedContext, group: SmallGroup, *, group_answers: int | None, church_answers: int, saves: int
) -> None:
    """`group_answers` None means everyone. `saves` is the draft's version: more than one has been edited."""
    session = ctx.session
    report = session.scalars(
        select(SmallGroupReport)
        .where(
            SmallGroupReport.small_group_id == group.id,
            SmallGroupReport.held,
            SmallGroupReport.meeting_date >= ctx.today - timedelta(days=NOT_FILED_WINDOW_DAYS),
            ~exists().where(ReportConversation.report_id == SmallGroupReport.id),
        )
        .order_by(SmallGroupReport.meeting_date.desc())
        .limit(1)
    ).one()
    meeting_date = report.meeting_date
    session.delete(report)
    session.flush()  # Before the draft takes its date.
    roster = roster_on_date(session, group.id, meeting_date)
    leader_id = next(p.member_id for p in roster if p.role == SmallGroupRole.LEADER)
    started_at = datetime.combine(meeting_date, time(19, 30), MANAGUA_TZ)
    session.add(
        SmallGroupReport(
            small_group=group,
            meeting_date=meeting_date,
            address=group.meeting_address,
            status=ReportStatus.DRAFT,
            version=saves,
            started_by_member_id=leader_id,
            started_at=started_at,
            last_edited_by_member_id=leader_id if saves > 1 else None,
            last_edited_at=started_at + timedelta(minutes=20) if saves > 1 else None,
            attendances=[
                SmallGroupReportAttendance(
                    member_id=person.member_id,
                    guest_id=person.guest_id,
                    attended_group=True if group_answers is None or index < group_answers else None,
                    attended_church=True if index < church_answers else None,
                )
                for index, person in enumerate(roster)
            ],
        )
    )
