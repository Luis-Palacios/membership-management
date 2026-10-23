from sqlalchemy import ColumnElement, Select, and_, func, select, true
from sqlalchemy.orm import aliased, joinedload

from membership_management.data.members.models import Member
from membership_management.data.small_groups.models import (
    ReportConversation,
    ReportConversationComment,
    ReportConversationRead,
    SmallGroup,
    SmallGroupReport,
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
            ReportConversation.section.label("section"),
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


def lock_conversation_query(conversation_id: int) -> Select:
    return select(ReportConversation.id).where(ReportConversation.id == conversation_id).with_for_update()


def comment_query(comment_id: int) -> Select:
    """One comment with its thread and the thread's report (for the scope check)."""
    return (
        select(ReportConversationComment)
        .where(ReportConversationComment.id == comment_id)
        .options(
            joinedload(ReportConversationComment.conversation).joinedload(ReportConversation.report),
            joinedload(ReportConversationComment.conversation).joinedload(ReportConversation.resolved_by),
        )
    )


def newest_live_comment_query(conversation_id: int) -> Select:
    return (
        select(
            ReportConversationComment.id.label("id"),
            ReportConversationComment.created_at.label("created_at"),
            ReportConversationComment.side.label("side"),
            ReportConversationComment.author_user_id.label("author_user_id"),
        )
        .where(
            ReportConversationComment.conversation_id == conversation_id,
            ReportConversationComment.deleted_at.is_(None),
        )
        .order_by(ReportConversationComment.created_at.desc(), ReportConversationComment.id.desc())
        .limit(1)
    )


def _audience_filters(group_ids: frozenset[int] | None) -> list[ColumnElement[bool]]:
    return [] if group_ids is None else [SmallGroupReport.small_group_id.in_(group_ids)]


def _needs_reply(my_side: str) -> ColumnElement[bool]:
    return and_(ReportConversation.status == "open", ReportConversation.last_comment_side != my_side)


def inbox_counts_query(group_ids: frozenset[int] | None, my_side: str) -> Select:
    """The three tab counts in one pass. `open` includes `reply`."""
    return (
        select(
            func.count().filter(_needs_reply(my_side)).label("reply"),
            func.count().filter(ReportConversation.status == "open").label("open"),
            func.count().filter(ReportConversation.status == "resolved").label("resolved"),
        )
        .select_from(ReportConversation)
        .join(SmallGroupReport, SmallGroupReport.id == ReportConversation.report_id)
        .where(*_audience_filters(group_ids))
    )


def needs_reply_count_query(group_ids: frozenset[int] | None, my_side: str) -> Select:
    """The sidebar badge: only the `reply` count, so nothing else is aggregated."""
    return (
        select(func.count())
        .select_from(ReportConversation)
        .join(SmallGroupReport, SmallGroupReport.id == ReportConversation.report_id)
        .where(_needs_reply(my_side), *_audience_filters(group_ids))
    )


def _tab_filter(tab: str, my_side: str) -> ColumnElement[bool]:
    if tab == "reply":
        return _needs_reply(my_side)
    return ReportConversation.status == ("resolved" if tab == "resolved" else "open")


def inbox_total_query(
    group_ids: frozenset[int] | None, my_side: str, tab: str, small_group_id: int | None
) -> Select:
    query = (
        select(func.count())
        .select_from(ReportConversation)
        .join(SmallGroupReport, SmallGroupReport.id == ReportConversation.report_id)
        .where(_tab_filter(tab, my_side), *_audience_filters(group_ids))
    )
    if small_group_id is not None:
        query = query.where(SmallGroupReport.small_group_id == small_group_id)
    return query


def inbox_rows_query(
    group_ids: frozenset[int] | None,
    user_id: str,
    my_side: str,
    tab: str,
    small_group_id: int | None,
    limit: int,
    offset: int,
) -> Select:
    """One page of threads, newest activity first, each with its newest comment (lateral join).

    The comment shown is the newest non-deleted one; a thread whose comments are all deleted shows its
    newest (deleted) one instead, so every row has a `lastComment`. The page is cut first (`page`), so
    the per-thread comment lookups run for the rows returned, not for every thread in the audience.
    """
    page = (
        select(ReportConversation.id.label("id"))
        .join(SmallGroupReport, SmallGroupReport.id == ReportConversation.report_id)
        .where(_tab_filter(tab, my_side), *_audience_filters(group_ids))
        .order_by(ReportConversation.last_comment_at.desc(), ReportConversation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if small_group_id is not None:
        page = page.where(SmallGroupReport.small_group_id == small_group_id)
    page_ids = page.subquery("page")
    last_comment = (
        select(
            ReportConversationComment.author_user_id.label("author_user_id"),
            ReportConversationComment.body.label("body"),
            ReportConversationComment.created_at.label("created_at"),
            ReportConversationComment.deleted_at.label("deleted_at"),
            Member.name.label("author_name"),
        )
        .join(Member, Member.id == ReportConversationComment.author_member_id)
        .where(ReportConversationComment.conversation_id == ReportConversation.id)
        .order_by(
            ReportConversationComment.deleted_at.is_not(None),
            ReportConversationComment.created_at.desc(),
            ReportConversationComment.id.desc(),
        )
        .limit(1)
        .lateral("last_comment")
    )
    comment_count = (
        select(func.count(ReportConversationComment.id))
        .where(
            ReportConversationComment.conversation_id == ReportConversation.id,
            ReportConversationComment.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    about = aliased(Member)
    resolver = aliased(Member)
    read = aliased(ReportConversationRead)
    query = (
        select(
            ReportConversation.id.label("id"),
            ReportConversation.status.label("status"),
            ReportConversation.last_comment_at.label("last_comment_at"),
            ReportConversation.last_comment_side.label("last_comment_side"),
            ReportConversation.last_comment_user_id.label("last_comment_user_id"),
            read.last_read_at.label("last_read_at"),
            about.id.label("member_id"),
            about.name.label("member_name"),
            ReportConversation.section.label("section"),
            resolver.id.label("resolver_id"),
            resolver.name.label("resolver_name"),
            SmallGroup.id.label("group_id"),
            SmallGroup.name.label("group_name"),
            SmallGroup.closed_at.label("group_closed_at"),
            SmallGroupReport.id.label("report_id"),
            SmallGroupReport.meeting_date.label("meeting_date"),
            last_comment.c.author_user_id.label("lc_author_user_id"),
            last_comment.c.author_name.label("lc_author_name"),
            last_comment.c.body.label("lc_body"),
            last_comment.c.created_at.label("lc_created_at"),
            last_comment.c.deleted_at.label("lc_deleted_at"),
            comment_count.label("comment_count"),
        )
        .select_from(page_ids)
        .join(ReportConversation, ReportConversation.id == page_ids.c.id)
        .join(SmallGroupReport, SmallGroupReport.id == ReportConversation.report_id)
        .join(SmallGroup, SmallGroup.id == SmallGroupReport.small_group_id)
        # Outer: a section thread has no member.
        .outerjoin(about, about.id == ReportConversation.member_id)
        .outerjoin(resolver, resolver.id == ReportConversation.resolved_by_member_id)
        .outerjoin(read, and_(read.conversation_id == ReportConversation.id, read.user_id == user_id))
        .join(last_comment, true())
        .order_by(ReportConversation.last_comment_at.desc(), ReportConversation.id.desc())
    )
    return query
