from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased, joinedload

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
    ReportConversation,
    ReportConversationComment,
    ReportConversationRead,
    SmallGroupReportAttendance,
)


def member_on_report_query(report_id: int, member_id: int) -> Select:
    return select(SmallGroupReportAttendance.id).where(
        SmallGroupReportAttendance.report_id == report_id,
        SmallGroupReportAttendance.member_id == member_id,
    )


def conversation_query(conversation_id: int) -> Select:
    """One thread with its report (for the scope check) and the resolver."""
    return (
        select(ReportConversation)
        .where(ReportConversation.id == conversation_id)
        .options(joinedload(ReportConversation.report), joinedload(ReportConversation.resolved_by))
    )


def report_member_conversation_query(report_id: int, member_id: int) -> Select:
    return (
        select(ReportConversation)
        .where(ReportConversation.report_id == report_id, ReportConversation.member_id == member_id)
        .options(joinedload(ReportConversation.resolved_by))
    )


def report_conversation_summaries_query(report_id: int, user_id: str) -> Select:
    """The report's threads with the live comment count and the caller's `last_read_at`."""
    comment_count = (
        select(func.count(ReportConversationComment.id))
        .where(
            ReportConversationComment.conversation_id == ReportConversation.id,
            ReportConversationComment.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    read = aliased(ReportConversationRead)
    return (
        select(
            ReportConversation.id.label("id"),
            ReportConversation.member_id.label("member_id"),
            ReportConversation.status.label("status"),
            comment_count.label("comment_count"),
            ReportConversation.last_comment_at.label("last_comment_at"),
            ReportConversation.last_comment_side.label("last_comment_side"),
            ReportConversation.last_comment_user_id.label("last_comment_user_id"),
            read.last_read_at.label("last_read_at"),
        )
        .outerjoin(read, (read.conversation_id == ReportConversation.id) & (read.user_id == user_id))
        .where(ReportConversation.report_id == report_id)
        .order_by(ReportConversation.last_comment_at.desc(), ReportConversation.id)
    )


def thread_comments_query(conversation_id: int) -> Select:
    """Comments oldest first, with the author's name."""
    return (
        select(
            ReportConversationComment.id.label("id"),
            ReportConversationComment.author_user_id.label("author_user_id"),
            ReportConversationComment.author_member_id.label("author_member_id"),
            Member.name.label("author_name"),
            ReportConversationComment.side.label("side"),
            ReportConversationComment.body.label("body"),
            ReportConversationComment.created_at.label("created_at"),
            ReportConversationComment.edited_at.label("edited_at"),
            ReportConversationComment.deleted_at.label("deleted_at"),
        )
        .join(Member, Member.id == ReportConversationComment.author_member_id)
        .where(ReportConversationComment.conversation_id == conversation_id)
        .order_by(ReportConversationComment.created_at, ReportConversationComment.id)
    )


def last_read_query(conversation_id: int, user_id: str) -> Select:
    return select(ReportConversationRead.last_read_at).where(
        ReportConversationRead.conversation_id == conversation_id,
        ReportConversationRead.user_id == user_id,
    )
