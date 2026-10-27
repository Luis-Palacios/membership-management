from datetime import datetime, time, timedelta

from sqlalchemy import select

from membership_management.data.members.models import Member, MemberSex
from membership_management.data.seed import fixtures
from membership_management.data.seed.context import MANAGUA_TZ, SeedContext
from membership_management.data.small_groups.models import (
    ReportConversation,
    ReportConversationComment,
    ReportConversationCommentRevision,
    SmallGroup,
    SmallGroupMember,
    SmallGroupReport,
    SmallGroupRole,
)

ELDER_COUNT = 2
HOURS_BETWEEN_COMMENTS = 7


def seed_report_conversations(ctx: SeedContext) -> None:
    """Threads in every state (waiting for each side, resolved, an edited and a deleted comment), on
    attendance rows and on report sections.

    There are no elders or users in the seed, so the elders' side is written by two members who lead
    nothing, under made-up user ids (`seed-elder-N`, `seed-user-<member id>`) that no auth-server
    account matches: every comment shows as someone else's, whoever you sign in as.
    """
    session = ctx.session
    leader_ids = {
        member_id
        for member_id in session.scalars(
            select(SmallGroupMember.member_id).where(SmallGroupMember.role != SmallGroupRole.MEMBER)
        )
        if member_id is not None
    }
    elders = _pick_elders(ctx, leader_ids)
    elder_member_ids = {member_id for member_id, _ in elders}
    now_cap = datetime.combine(ctx.today, time(8, 0), MANAGUA_TZ)
    groups = list(session.scalars(select(SmallGroup).order_by(SmallGroup.id)))

    for script in fixtures.CONVERSATION_THREADS:
        reports = list(
            session.scalars(
                select(SmallGroupReport)
                .where(SmallGroupReport.small_group_id == groups[script.group].id, SmallGroupReport.held)
                .order_by(SmallGroupReport.meeting_date.desc())
            )
        )
        if script.section is not None:
            # Only a section with items can get a thread.
            report = next(
                r for r in reports[script.report :] if any(i.section == script.section for i in r.items)
            )
            about_member_id = None
        else:
            report = reports[script.report]
            # Somebody who missed the meeting if possible (that's what elders ask about), never an elder.
            rows = [a for a in report.attendances if a.member_id not in elder_member_ids]
            about_member_id = next((a for a in rows if not a.attended_group), rows[0]).member_id
        leader_id = report.submitted_by_member_id
        started = datetime.combine(report.meeting_date, time(21, 0), MANAGUA_TZ) + timedelta(days=1, hours=1)

        elder_turn = 0
        comments: list[ReportConversationComment] = []
        for n, spec in enumerate(script.comments):
            created_at = min(started + timedelta(hours=HOURS_BETWEEN_COMMENTS * n), now_cap)
            if spec.side == "elders":
                # The elders' side alternates between the two elders.
                member_id, user_id = elders[elder_turn % ELDER_COUNT]
                elder_turn += 1
            else:
                member_id, user_id = leader_id, f"seed-user-{leader_id}"
            comment = ReportConversationComment(
                author_user_id=user_id,
                author_member_id=member_id,
                side=spec.side,
                body=spec.body,
                created_at=created_at,
            )
            if spec.edited_from is not None:
                comment.edited_at = created_at + timedelta(minutes=20)
                comment.revisions.append(
                    ReportConversationCommentRevision(body=spec.edited_from, replaced_at=comment.edited_at)
                )
            if spec.deleted:
                comment.deleted_at = created_at + timedelta(minutes=5)
            comments.append(comment)

        # last_comment_* follow the newest comment that wasn't deleted.
        newest = [c for c in comments if c.deleted_at is None][-1]
        conversation = ReportConversation(
            report_id=report.id,
            member_id=about_member_id,
            section=script.section,
            status="open",
            created_by_user_id=comments[0].author_user_id,
            created_at=comments[0].created_at,
            last_comment_at=newest.created_at,
            last_comment_side=newest.side,
            last_comment_user_id=newest.author_user_id,
            comments=comments,
        )
        if script.resolved_by is not None:
            resolver = elders[0] if script.resolved_by == "elders" else (leader_id, f"seed-user-{leader_id}")
            conversation.status = "resolved"
            conversation.resolved_by_member_id, conversation.resolved_by_user_id = resolver
            conversation.resolved_at = min(newest.created_at + timedelta(hours=2), now_cap)
        session.add(conversation)
    session.flush()


def _pick_elders(ctx: SeedContext, leader_ids: set[int]) -> list[tuple[int, str]]:
    """Two members who lead nothing, as (member id, made-up user id)."""
    candidates = list(
        ctx.session.scalars(
            select(Member)
            .where(Member.sex == MemberSex.MALE, Member.id.not_in(leader_ids))
            .order_by(Member.id)
        )
    )
    return [(m.id, f"seed-elder-{i + 1}") for i, m in enumerate(ctx.rng.sample(candidates, ELDER_COUNT))]
