from datetime import datetime
from typing import Literal

from sqlalchemy import Row, func, select
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
    needs_reply_count_query,
    newest_live_comment_query,
    person_on_report_query,
    report_anchor_conversation_query,
    report_conversation_summaries_query,
    section_conversation_summaries_query,
    section_has_items_query,
    thread_comments_query,
)
from membership_management.data.small_groups.models import (
    ConversationSide,
    ReportConversation,
    ReportConversationComment,
    ReportConversationCommentRevision,
    ReportConversationRead,
    ReportSection,
)
from membership_management.data.small_groups.results import (
    CommentAuthor,
    ConversationComment,
    ConversationMember,
    ConversationPerson,
    ConversationSummaries,
    ConversationSummary,
    ConversationThread,
    InboxCounts,
    InboxGroup,
    InboxLastComment,
    InboxPage,
    InboxReport,
    InboxRow,
    PersonKey,
)

# What a thread is about: a member's or a guest's attendance row (`("member"|"guest", id)`) or a report
# section.
ConversationAnchor = PersonKey | ReportSection


class MemberNotOnReportError(Exception):
    """The member or guest has no attendance row on the report (or the report is a no meeting): 422."""


class SectionEmptyError(Exception):
    """Starting a thread on a section with no text (or on a no meeting, which has none): 422."""


class ConversationNotFoundError(Exception):
    """No thread yet for this report and anchor: 404 `No conversation yet.`"""


class ConversationRaceError(Exception):
    """Two requests kept creating the same thread at once: 409, try again."""


class NotYourCommentError(Exception):
    """Editing or deleting someone else's comment (rule 8, 9): 403."""


class StaleThreadError(Exception):
    """Resolving a thread that got a comment the resolver never saw: 409, the client re-renders."""


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


def _section(value: str | None) -> ReportSection | None:
    """The stored `section` column (plain VARCHAR) as the enum."""
    return ReportSection(value) if value is not None else None


def get_conversation(session: Session, conversation_id: int) -> ReportConversation | None:
    return session.scalars(conversation_query(conversation_id)).one_or_none()


def get_report_conversations(
    session: Session, report_id: int, user_id: str, my_side: ConversationSide
) -> ConversationSummaries:
    rows = session.execute(report_conversation_summaries_query(report_id, user_id)).all()
    summaries = [_summary(row, user_id, my_side) for row in rows]
    return ConversationSummaries(
        conversations=summaries,
        total=len(summaries),
        needs_my_reply=sum(1 for s in summaries if s.needs_my_reply),
    )


def get_section_conversations(
    session: Session, report_ids: frozenset[int], user_id: str, my_side: ConversationSide
) -> dict[int, dict[ReportSection, ConversationSummary]]:
    """The section threads of several reports, by report id then section, in one query (prayer &
    follow-up shared entries). A report or section with no thread is absent."""
    by_report: dict[int, dict[ReportSection, ConversationSummary]] = {}
    if not report_ids:
        return by_report
    for row in session.execute(section_conversation_summaries_query(report_ids, user_id)):
        summary = _summary(row, user_id, my_side)
        if summary.section is not None:
            by_report.setdefault(row.report_id, {})[summary.section] = summary
    return by_report


def _person(
    member_id: int | None, member_name: str | None, guest_id: int | None, guest_name: str | None
) -> ConversationPerson | None:
    """Who a thread is about (None for a section thread)."""
    if member_id is not None and member_name is not None:
        return ConversationPerson("member", member_id, member_name)
    if guest_id is not None and guest_name is not None:
        return ConversationPerson("guest", guest_id, guest_name)
    return None


def _summary(row: Row, user_id: str, my_side: ConversationSide) -> ConversationSummary:
    """A summaries-query row as the caller sees it (rules 11, 12)."""
    return ConversationSummary(
        id=row.id,
        member_id=row.member_id,
        guest_id=row.guest_id,
        person=_person(row.member_id, row.member_name, row.guest_id, row.guest_name),
        section=_section(row.section),
        status=row.status,
        comment_count=row.comment_count,
        unread=is_unread(row.last_comment_user_id, row.last_comment_at, row.last_read_at, user_id),
        needs_my_reply=needs_reply(row.status, row.last_comment_side, my_side),
        last_comment_at=row.last_comment_at,
    )


def get_report_anchor_conversation(
    session: Session, report_id: int, anchor: ConversationAnchor
) -> ReportConversation:
    """The report's thread about a member's or a guest's row, or a section.

    An existing thread is returned even if the person's attendance row is gone or the section was
    cleared (editing a report can do either; the thread and its replies must stay reachable). With no
    thread, a person who isn't on the report raises `MemberNotOnReportError` (422), otherwise
    `ConversationNotFoundError` (404), for a section whatever its text.
    """
    conversation = session.scalars(report_anchor_conversation_query(report_id, anchor)).one_or_none()
    if conversation is not None:
        return conversation
    if (
        not isinstance(anchor, ReportSection)
        and session.scalar(person_on_report_query(report_id, anchor)) is None
    ):
        raise MemberNotOnReportError
    raise ConversationNotFoundError


def _check_can_start(session: Session, report_id: int, anchor: ConversationAnchor) -> None:
    """A new thread needs the member or guest to have an attendance row (rule 1) or the section to have
    an item (report tags rule 18)."""
    if isinstance(anchor, ReportSection):
        if not session.scalar(section_has_items_query(report_id, anchor)):
            raise SectionEmptyError
    elif session.scalar(person_on_report_query(report_id, anchor)) is None:
        raise MemberNotOnReportError


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
    member = conversation.member
    guest = conversation.guest
    return ConversationThread(
        id=conversation.id,
        member_id=conversation.member_id,
        member_name=member.name if member is not None else None,
        guest_id=conversation.guest_id,
        person=_person(
            conversation.member_id,
            member.name if member is not None else None,
            conversation.guest_id,
            guest.name if guest is not None else None,
        ),
        section=_section(conversation.section),
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
            # Never backwards: two requests can read the clock in one order and commit in the other.
            set_={
                "last_read_at": func.greatest(ReportConversationRead.last_read_at, stmt.excluded.last_read_at)
            },
        )
    )


def mark_read(session: Session, conversation_id: int, user_id: str) -> None:
    """Upsert the caller's `last_read_at` to now."""
    _upsert_read(session, conversation_id, user_id, _db_now(session))
    session.commit()


def _lock(session: Session, conversation_id: int) -> None:
    """Serialise writers on one thread, so the denormalised columns can't be overwritten out of order."""
    session.execute(lock_conversation_query(conversation_id))


def _lock_and_refresh(session: Session, conversation: ReportConversation) -> None:
    """Take the thread lock, then reload the thread, so what is checked next is what the last writer left."""
    _lock(session, conversation.id)
    session.refresh(conversation)


def _lock_and_refresh_comment(session: Session, comment: ReportConversationComment) -> None:
    """Lock the comment's thread, then reload the comment and the thread: the latest committed state."""
    _lock(session, comment.conversation_id)
    session.refresh(comment)
    session.refresh(comment.conversation)


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
    session: Session,
    report_id: int,
    anchor: ConversationAnchor,
    user_id: str,
    side: ConversationSide,
    now: datetime,
) -> ReportConversation:
    """The thread for the row or section, creating it when missing. A unique violation means someone
    else just created it: look again (once), then give up.

    Only a new thread is checked by `_check_can_start`; replying to an existing one works even after a
    report edit removed the row or cleared the section.
    """
    section = anchor if isinstance(anchor, ReportSection) else None
    member_id = anchor[1] if not isinstance(anchor, ReportSection) and anchor[0] == "member" else None
    guest_id = anchor[1] if not isinstance(anchor, ReportSection) and anchor[0] == "guest" else None
    for _ in range(2):
        existing = session.scalars(report_anchor_conversation_query(report_id, anchor)).one_or_none()
        if existing is not None:
            return existing
        _check_can_start(session, report_id, anchor)
        try:
            with session.begin_nested():
                conversation = ReportConversation(
                    report_id=report_id,
                    member_id=member_id,
                    guest_id=guest_id,
                    section=section,
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
    anchor: ConversationAnchor,
    *,
    user_id: str,
    author_member_id: int,
    side: ConversationSide,
    body: str,
) -> ReportConversation:
    """Rule 1, 5, 6, 10: create the thread if needed, reopen it if resolved, add the comment and mark
    the thread read for the author, in one transaction."""
    conversation = _get_or_create(session, report_id, anchor, user_id, side, _db_now(session))
    session.flush()
    _lock_and_refresh(session, conversation)
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
    """Rule 8: the old text goes to a revision; `last_comment_at` doesn't move.

    Takes the thread lock and reloads the comment before checking `deleted_at`, so an edit that raced a
    delete sees the delete and answers `CommentDeletedError` instead of changing a deleted comment.
    """
    if comment.author_user_id != user_id:
        raise NotYourCommentError
    _lock_and_refresh_comment(session, comment)
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
    _lock_and_refresh_comment(session, comment)
    if comment.deleted_at is None:
        comment.deleted_at = _db_now(session)
        session.flush()
        _sync_last_comment(session, conversation)
    session.commit()  # also when there was nothing to do: ends the transaction and releases the lock
    return conversation


def _reopen(conversation: ReportConversation) -> None:
    conversation.status = "open"
    conversation.resolved_by_user_id = None
    conversation.resolved_by_member_id = None
    conversation.resolved_at = None


def resolve(
    session: Session,
    conversation: ReportConversation,
    *,
    user_id: str,
    member_id: int,
    last_comment_id: int | None,
) -> ReportConversation:
    """Idempotent: resolving a resolved thread keeps the first resolver, with no staleness check.

    Takes the thread lock before looking at the status, like `add_comment`, so two resolvers can't both
    see `open`. `last_comment_id` is the newest comment the caller saw (None: no live comments); if the
    newest non-deleted comment is another one, the thread is left open and `StaleThreadError` is raised,
    so nobody resolves over a comment they haven't read.
    """
    _lock_and_refresh(session, conversation)
    if conversation.status != "resolved":
        newest = session.execute(newest_live_comment_query(conversation.id)).first()
        if (newest.id if newest is not None else None) != last_comment_id:
            session.rollback()  # nothing was changed; releases the lock
            raise StaleThreadError
        conversation.status = "resolved"
        conversation.resolved_by_user_id = user_id
        conversation.resolved_by_member_id = member_id
        conversation.resolved_at = _db_now(session)
    session.commit()  # also when already resolved: ends the transaction and releases the lock
    return conversation


def reopen(session: Session, conversation: ReportConversation) -> ReportConversation:
    """Idempotent. Locks and reloads the thread first, for the same reason as `resolve`."""
    _lock_and_refresh(session, conversation)
    if conversation.status != "open":
        _reopen(conversation)
    session.commit()  # also when already open: ends the transaction and releases the lock
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
            member=ConversationMember(member_id=r.member_id, name=r.member_name)
            if r.member_id is not None
            else None,
            person=_person(r.member_id, r.member_name, r.guest_id, r.guest_name),
            section=_section(r.section),
            group=InboxGroup(
                id=r.group_id,
                name=r.group_name,
                closed=r.group_closed_at is not None,
                audience=r.group_audience,
            ),
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
