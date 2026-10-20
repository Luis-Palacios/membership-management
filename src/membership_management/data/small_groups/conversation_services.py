from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from membership_management.data.small_groups.conversation_queries import (
    comment_query,
    conversation_query,
    inbox_counts_query,
    inbox_rows_query,
    inbox_total_query,
    last_read_query,
    lock_conversation_query,
    member_on_report_query,
    needs_reply_count_query,
    newest_live_comment_query,
    report_conversation_summaries_query,
    report_member_conversation_query,
    thread_comments_query,
)
from membership_management.data.small_groups.models import (
    ConversationSide,
    ReportConversation,
    ReportConversationComment,
    ReportConversationCommentRevision,
    ReportConversationRead,
)
from membership_management.data.small_groups.results import (
    CommentAuthor,
    ConversationComment,
    ConversationMember,
    ConversationSummaries,
    ConversationSummary,
    ConversationThread,
    InboxCounts,
    InboxGroup,
    InboxLastComment,
    InboxPage,
    InboxReport,
    InboxRow,
)


class MemberNotOnReportError(Exception):
    """The member has no attendance row on the report (or the report is a no meeting): 422."""


class ConversationNotFoundError(Exception):
    """No thread yet for this report and member: 404 `No conversation yet.`"""


class ConversationRaceError(Exception):
    """Two requests kept creating the same thread at once: 409, try again."""


class NotYourCommentError(Exception):
    """Editing or deleting someone else's comment (rule 8, 9): 403."""


class CommentDeletedError(Exception):
    """Editing a deleted comment: 409."""


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


def _db_now(session: Session) -> datetime:
    """The database clock, so comment times and read times compare on one clock.

    `clock_timestamp()`, not `now()`: a request that waited for the thread lock must not stamp its
    comment before the one it queued behind.
    """
    return session.execute(select(func.clock_timestamp())).scalar_one()


def _upsert_read(session: Session, conversation_id: int, user_id: str, at: datetime) -> None:
    stmt = insert(ReportConversationRead).values(
        user_id=user_id, conversation_id=conversation_id, last_read_at=at
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ReportConversationRead.user_id, ReportConversationRead.conversation_id],
            set_={"last_read_at": stmt.excluded.last_read_at},
        )
    )


def mark_read(session: Session, conversation_id: int, user_id: str) -> None:
    """Upsert the caller's `last_read_at` to now."""
    _upsert_read(session, conversation_id, user_id, _db_now(session))
    session.commit()


def _lock(session: Session, conversation_id: int) -> None:
    """Serialise writers on one thread, so the denormalised columns can't be overwritten out of order."""
    session.execute(lock_conversation_query(conversation_id))


def _sync_last_comment(session: Session, conversation: ReportConversation) -> None:
    """Point `last_comment_*` at the newest non-deleted comment.

    A thread whose comments are all deleted keeps its last values: it stays where it was in the
    inbox and shows only stubs.
    """
    newest = session.execute(newest_live_comment_query(conversation.id)).first()
    if newest is not None:
        conversation.last_comment_at = newest.created_at
        conversation.last_comment_side = newest.side
        conversation.last_comment_user_id = newest.author_user_id


def _get_or_create(
    session: Session, report_id: int, member_id: int, user_id: str, side: ConversationSide, now: datetime
) -> ReportConversation:
    """The thread for the row, creating it when missing. A unique violation means someone else just
    created it: look again (once), then give up."""
    for _ in range(2):
        existing = session.scalars(report_member_conversation_query(report_id, member_id)).one_or_none()
        if existing is not None:
            return existing
        try:
            with session.begin_nested():
                conversation = ReportConversation(
                    report_id=report_id,
                    member_id=member_id,
                    status="open",
                    created_by_user_id=user_id,
                    created_at=now,
                    last_comment_at=now,
                    last_comment_side=side,
                    last_comment_user_id=user_id,
                )
                session.add(conversation)
        except IntegrityError:
            continue
        return conversation
    raise ConversationRaceError


def add_comment(
    session: Session,
    report_id: int,
    member_id: int,
    *,
    user_id: str,
    author_member_id: int,
    side: ConversationSide,
    body: str,
) -> ReportConversation:
    """Rule 1, 5, 6, 10: create the thread if needed, reopen it if resolved, add the comment and mark
    the thread read for the author, in one transaction."""
    if session.scalar(member_on_report_query(report_id, member_id)) is None:
        raise MemberNotOnReportError
    conversation = _get_or_create(session, report_id, member_id, user_id, side, _db_now(session))
    session.flush()
    _lock(session, conversation.id)
    session.refresh(conversation)
    now = _db_now(session)
    session.add(
        ReportConversationComment(
            conversation_id=conversation.id,
            author_user_id=user_id,
            author_member_id=author_member_id,
            side=side,
            body=body,
            created_at=now,
        )
    )
    conversation.last_comment_at = now
    conversation.last_comment_side = side
    conversation.last_comment_user_id = user_id
    _reopen(conversation)
    _upsert_read(session, conversation.id, user_id, now)
    session.commit()
    return conversation


def get_comment(session: Session, comment_id: int) -> ReportConversationComment | None:
    return session.scalars(comment_query(comment_id)).one_or_none()


def edit_comment(
    session: Session, comment: ReportConversationComment, *, user_id: str, body: str
) -> ReportConversation:
    """Rule 8: the old text goes to a revision; `last_comment_at` doesn't move."""
    if comment.author_user_id != user_id:
        raise NotYourCommentError
    if comment.deleted_at is not None:
        raise CommentDeletedError
    now = _db_now(session)
    if body != comment.body:
        session.add(
            ReportConversationCommentRevision(comment_id=comment.id, body=comment.body, replaced_at=now)
        )
        comment.body = body
        comment.edited_at = now
    session.commit()
    return comment.conversation


def delete_comment(
    session: Session, comment: ReportConversationComment, *, user_id: str
) -> ReportConversation:
    """Rule 9: soft delete (idempotent); the denormalised fields follow the newest remaining comment."""
    if comment.author_user_id != user_id:
        raise NotYourCommentError
    conversation = comment.conversation
    if comment.deleted_at is None:
        _lock(session, conversation.id)
        comment.deleted_at = _db_now(session)
        session.flush()
        _sync_last_comment(session, conversation)
        session.commit()
    return conversation


def _reopen(conversation: ReportConversation) -> None:
    conversation.status = "open"
    conversation.resolved_by_user_id = None
    conversation.resolved_by_member_id = None
    conversation.resolved_at = None


def resolve(
    session: Session, conversation: ReportConversation, *, user_id: str, member_id: int
) -> ReportConversation:
    """Idempotent: resolving a resolved thread keeps the first resolver."""
    if conversation.status != "resolved":
        conversation.status = "resolved"
        conversation.resolved_by_user_id = user_id
        conversation.resolved_by_member_id = member_id
        conversation.resolved_at = _db_now(session)
        session.commit()
    return conversation


def reopen(session: Session, conversation: ReportConversation) -> ReportConversation:
    """Idempotent."""
    if conversation.status != "open":
        _reopen(conversation)
        session.commit()
    return conversation


InboxTab = Literal["reply", "open", "resolved"]
EXCERPT_LENGTH = 160


def _excerpt(body: str) -> str:
    """First 160 characters with whitespace collapsed."""
    return " ".join(body.split())[:EXCERPT_LENGTH]


def get_inbox(
    session: Session,
    *,
    group_ids: frozenset[int] | None,
    user_id: str,
    my_side: ConversationSide,
    tab: InboxTab,
    small_group_id: int | None,
    limit: int,
    offset: int,
) -> InboxPage:
    """Rules 11, 12, 15. `group_ids` is the caller's audience (None = every group).

    The three tab counts ignore `small_group_id` (they are the whole inbox, so the tabs don't jump when
    a group is picked); `total` is the filtered tab.
    """
    if group_ids is not None and not group_ids:
        return InboxPage(items=[], counts=InboxCounts(reply=0, open=0, resolved=0), total=0)
    counts = session.execute(inbox_counts_query(group_ids, my_side)).one()
    if small_group_id is not None and group_ids is not None and small_group_id not in group_ids:
        return InboxPage(items=[], counts=InboxCounts(*counts), total=0)
    total = session.scalar(inbox_total_query(group_ids, my_side, tab, small_group_id)) or 0
    rows = session.execute(
        inbox_rows_query(group_ids, user_id, my_side, tab, small_group_id, limit, offset)
    ).all()
    items = [
        InboxRow(
            id=r.id,
            status=r.status,
            needs_my_reply=needs_reply(r.status, r.last_comment_side, my_side),
            unread=is_unread(r.last_comment_user_id, r.last_comment_at, r.last_read_at, user_id),
            member=ConversationMember(member_id=r.member_id, name=r.member_name),
            group=InboxGroup(id=r.group_id, name=r.group_name, closed=r.group_closed_at is not None),
            report=InboxReport(id=r.report_id, meeting_date=r.meeting_date),
            last_comment=InboxLastComment(
                author_name=r.lc_author_name,
                mine=r.lc_author_user_id == user_id,
                deleted=r.lc_deleted_at is not None,
                excerpt=None if r.lc_deleted_at is not None else _excerpt(r.lc_body),
                created_at=r.lc_created_at,
            ),
            resolved_by=ConversationMember(member_id=r.resolver_id, name=r.resolver_name)
            if r.resolver_id is not None
            else None,
            comment_count=r.comment_count,
        )
        for r in rows
    ]
    return InboxPage(items=items, counts=InboxCounts(*counts), total=total)


def count_needing_reply(
    session: Session, *, group_ids: frozenset[int] | None, my_side: ConversationSide
) -> int:
    if group_ids is not None and not group_ids:
        return 0
    return session.scalar(needs_reply_count_query(group_ids, my_side)) or 0
