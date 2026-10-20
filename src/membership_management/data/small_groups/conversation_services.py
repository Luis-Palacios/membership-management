from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from membership_management.data.small_groups.conversation_queries import (
    conversation_query,
    last_read_query,
    member_on_report_query,
    report_conversation_summaries_query,
    report_member_conversation_query,
    thread_comments_query,
)
from membership_management.data.small_groups.models import (
    ConversationSide,
    ReportConversation,
    ReportConversationRead,
)
from membership_management.data.small_groups.results import (
    CommentAuthor,
    ConversationComment,
    ConversationMember,
    ConversationSummaries,
    ConversationSummary,
    ConversationThread,
)


class MemberNotOnReportError(Exception):
    """The member has no attendance row on the report (or the report is a no meeting): 422."""


class ConversationNotFoundError(Exception):
    """No thread yet for this report and member: 404 `No conversation yet.`"""


def needs_reply(status: str, last_comment_side: str, my_side: ConversationSide) -> bool:
    """Rule 12: open, and the latest comment is on the other side from the caller."""
    return status == "open" and last_comment_side != my_side


def is_unread(
    last_comment_user_id: str, last_comment_at: datetime, last_read_at: datetime | None, user_id: str
) -> bool:
    """Rule 11: the newest comment is someone else's and newer than the caller's last read."""
    return last_comment_user_id != user_id and (last_read_at is None or last_read_at < last_comment_at)


def get_conversation(session: Session, conversation_id: int) -> ReportConversation | None:
    return session.scalars(conversation_query(conversation_id)).one_or_none()


def get_report_conversations(
    session: Session, report_id: int, user_id: str, my_side: ConversationSide
) -> ConversationSummaries:
    rows = session.execute(report_conversation_summaries_query(report_id, user_id)).all()
    summaries = [
        ConversationSummary(
            id=row.id,
            member_id=row.member_id,
            status=row.status,
            comment_count=row.comment_count,
            unread=is_unread(row.last_comment_user_id, row.last_comment_at, row.last_read_at, user_id),
            needs_my_reply=needs_reply(row.status, row.last_comment_side, my_side),
            last_comment_at=row.last_comment_at,
        )
        for row in rows
    ]
    return ConversationSummaries(
        conversations=summaries,
        total=len(summaries),
        needs_my_reply=sum(1 for s in summaries if s.needs_my_reply),
    )


def get_report_member_conversation(session: Session, report_id: int, member_id: int) -> ReportConversation:
    """The thread for a row of the report. Raises `MemberNotOnReportError` before looking for the thread."""
    if session.scalar(member_on_report_query(report_id, member_id)) is None:
        raise MemberNotOnReportError
    conversation = session.scalars(report_member_conversation_query(report_id, member_id)).one_or_none()
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


def build_thread(session: Session, conversation: ReportConversation, user_id: str) -> ConversationThread:
    """The thread as the caller sees it: deleted comments are stubs and their text is never read out."""
    last_read_at = session.scalar(last_read_query(conversation.id, user_id))
    comments: list[ConversationComment] = []
    first_unread: int | None = None
    for row in session.execute(thread_comments_query(conversation.id)):
        deleted = row.deleted_at is not None
        if (
            first_unread is None
            and not deleted
            and row.author_user_id != user_id
            and (last_read_at is None or row.created_at > last_read_at)
        ):
            first_unread = row.id
        comments.append(
            ConversationComment(
                id=row.id,
                author=CommentAuthor(member_id=row.author_member_id, name=row.author_name, side=row.side),
                body=None if deleted else row.body,
                created_at=row.created_at,
                edited_at=None if deleted else row.edited_at,
                deleted=deleted,
                mine=row.author_user_id == user_id,
            )
        )
    resolved_by = conversation.resolved_by
    return ConversationThread(
        id=conversation.id,
        member_id=conversation.member_id,
        status=conversation.status,
        resolved_by=ConversationMember(member_id=resolved_by.id, name=resolved_by.name)
        if resolved_by is not None
        else None,
        resolved_at=conversation.resolved_at,
        first_unread_comment_id=first_unread,
        comments=comments,
    )


def mark_read(session: Session, conversation_id: int, user_id: str) -> None:
    """Upsert the caller's `last_read_at` to now."""
    stmt = insert(ReportConversationRead).values(
        user_id=user_id, conversation_id=conversation_id, last_read_at=func.now()
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ReportConversationRead.user_id, ReportConversationRead.conversation_id],
            set_={"last_read_at": stmt.excluded.last_read_at},
        )
    )
    session.commit()
