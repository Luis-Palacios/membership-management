from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from membership_management.api.access import (
    OptionalSmallGroupScopeDep,
    SmallGroupScope,
    SmallGroupScopeDep,
    comment_side,
    conversation_access,
    conversation_group_ids,
)
from membership_management.api.current_member import CurrentMemberDep
from membership_management.api.dependencies import MembersSessionDep
from membership_management.api.jwt_auth import (
    AuthClaims,
    CurrentClaimsDep,
    get_current_claims,
    require_permission,
)
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.report_conversations import (
    CommentAuthorSchema,
    CommentBodySchema,
    ConversationAnchorSchema,
    ConversationCommentSchema,
    ConversationCountsSchema,
    ConversationPersonSchema,
    ConversationSummarySchema,
    ConversationThreadSchema,
    InboxCountsSchema,
    InboxGroupSchema,
    InboxItemSchema,
    InboxLastCommentSchema,
    InboxMemberSchema,
    InboxReportSchema,
    InboxSchema,
    NeedsMyReplyCountSchema,
    ReportConversationsSchema,
    ResolveBodySchema,
)
from membership_management.data.members.models import Member
from membership_management.data.small_groups.conversation_services import (
    CommentDeletedError,
    ConversationNotFoundError,
    ConversationRaceError,
    InboxTab,
    MemberNotOnReportError,
    NotYourCommentError,
    StaleThreadError,
    add_comment,
    build_thread,
    count_needing_reply,
    delete_comment,
    edit_comment,
    get_comment,
    get_conversation,
    get_inbox,
    get_report_conversations,
    get_report_member_conversation,
    mark_read,
    reopen,
    resolve,
)
from membership_management.data.small_groups.models import (
    ReportConversation,
    ReportConversationComment,
    SmallGroupReport,
)
from membership_management.data.small_groups.results import ConversationThread
from membership_management.data.small_groups.services import get_report

# No prefix: the routes live under both /small-group-reports/{id}/... and /report-conversations.
# Everyone in the report's observation audience can use them (no new permission, spec rule 4):
# `smallGroupReports: view` gets you in, `conversation_access` (one report) or `conversation_group_ids`
# (the inbox) decides what you see.
router = APIRouter(
    tags=["report-conversations"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)

# Every route but the sidebar badge (`/report-conversations/counts` answers 0 instead of 403).
_needs_reports_view = Depends(require_permission("smallGroupReports", "view"))


STALE_THREAD_DETAIL = "There's a new comment since you opened this."


class StaleConversationHTTPError(HTTPException):
    """409 whose body also carries the current thread (`conversation`); see its handler in `main.py`."""

    def __init__(self, thread: ConversationThreadSchema) -> None:
        super().__init__(status_code=409, detail=STALE_THREAD_DETAIL)
        self.thread = thread


def _http_error(exc: Exception) -> HTTPException:
    """Map a conversation domain error to its HTTP error (the staff app matches on status and `detail`)."""
    if isinstance(exc, MemberNotOnReportError):
        return HTTPException(status_code=422, detail="That person has no attendance row on this report.")
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=404, detail="No conversation yet.")
    if isinstance(exc, NotYourCommentError):
        return HTTPException(status_code=403, detail="That's not your comment.")
    if isinstance(exc, CommentDeletedError):
        return HTTPException(status_code=409, detail="That comment was deleted.")
    if isinstance(exc, ConversationRaceError):
        return HTTPException(
            status_code=409, detail="Someone else just started this conversation. Try again."
        )
    raise exc


def _report_or_404(
    db: MembersSessionDep, report_id: int, claims: AuthClaims, scope: SmallGroupScope
) -> SmallGroupReport:
    """The report when the caller is in its audience: 404 outside the scope, 403 outside the audience."""
    report = get_report(db, report_id, None if scope.full else scope.group_ids)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Small group report with ID {report_id} not found.")
    conversation_access(report, claims, scope)
    return report


def _linked_member(member: Member | None) -> Member:
    """Rule 5: every write needs a linked member (reading doesn't)."""
    if member is None:
        raise HTTPException(status_code=409, detail="Link your account to a member to comment.")
    return member


def _conversation_or_404(
    db: MembersSessionDep, conversation_id: int, claims: AuthClaims, scope: SmallGroupScope
) -> ReportConversation:
    conversation = get_conversation(db, conversation_id)
    if conversation is None or not scope.includes(conversation.report.small_group_id):
        raise HTTPException(status_code=404, detail=f"Conversation with ID {conversation_id} not found.")
    conversation_access(conversation.report, claims, scope)
    return conversation


def _thread_schema(thread: ConversationThread) -> ConversationThreadSchema:
    return ConversationThreadSchema(
        id=thread.id,
        anchor=ConversationAnchorSchema(member_id=thread.member_id),
        member=InboxMemberSchema(id=thread.member_id, name=thread.member_name),
        status=thread.status,
        resolved_by=ConversationPersonSchema(
            member_id=thread.resolved_by.member_id, name=thread.resolved_by.name
        )
        if thread.resolved_by is not None
        else None,
        resolved_at=thread.resolved_at,
        first_unread_comment_id=thread.first_unread_comment_id,
        comments=[
            ConversationCommentSchema(
                id=c.id,
                author=CommentAuthorSchema(
                    member_id=c.author.member_id, name=c.author.name, side=c.author.side
                ),
                body=c.body,
                created_at=c.created_at,
                edited_at=c.edited_at,
                deleted=c.deleted,
                mine=c.mine,
            )
            for c in thread.comments
        ],
    )


@router.get(
    "/small-group-reports/{report_id}/conversations",
    name="list_report_conversations",
    description="A report's threads with the row indicators: comment count, unread and needs my reply",
    dependencies=[_needs_reports_view],
)
def get_report_conversation_summaries(
    report_id: int, db: MembersSessionDep, claims: CurrentClaimsDep, scope: SmallGroupScopeDep
) -> ReportConversationsSchema:
    report = _report_or_404(db, report_id, claims, scope)
    result = get_report_conversations(db, report.id, claims.sub, comment_side(claims))
    return ReportConversationsSchema(
        conversations=[
            ConversationSummarySchema(
                id=s.id,
                anchor=ConversationAnchorSchema(member_id=s.member_id),
                status=s.status,
                comment_count=s.comment_count,
                unread=s.unread,
                needs_my_reply=s.needs_my_reply,
                last_comment_at=s.last_comment_at,
            )
            for s in result.conversations
        ],
        counts=ConversationCountsSchema(total=result.total, needs_my_reply=result.needs_my_reply),
    )


@router.get(
    "/small-group-reports/{report_id}/conversations/{member_id}",
    name="get_report_conversation",
    description="One person's thread on a report; 404 `No conversation yet.` when nobody has commented",
    dependencies=[_needs_reports_view],
)
def get_report_conversation(
    report_id: int,
    member_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
) -> ConversationThreadSchema:
    report = _report_or_404(db, report_id, claims, scope)
    try:
        conversation = get_report_member_conversation(db, report.id, member_id)
    except (MemberNotOnReportError, ConversationNotFoundError) as exc:
        raise _http_error(exc) from exc
    return _thread_schema(build_thread(db, conversation, claims.sub))


@router.post(
    "/report-conversations/{conversation_id}/read",
    name="mark_report_conversation_read",
    description="Mark the thread read for the caller (opening the panel); never done by a GET",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        _needs_reports_view,
        Depends(rate_limit("120/minute", scope="mark_report_conversation_read")),
    ],
)
def post_report_conversation_read(
    conversation_id: int, db: MembersSessionDep, claims: CurrentClaimsDep, scope: SmallGroupScopeDep
) -> Response:
    conversation = _conversation_or_404(db, conversation_id, claims, scope)
    mark_read(db, conversation.id, claims.sub)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/small-group-reports/{report_id}/conversations/{member_id}/comments",
    name="add_report_conversation_comment",
    description="Add a comment to a person's thread: creates the thread, reopens it when resolved",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        _needs_reports_view,
        Depends(rate_limit("30/minute", scope="add_report_conversation_comment")),
    ],
)
def post_report_conversation_comment(
    report_id: int,
    member_id: int,
    body: CommentBodySchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ConversationThreadSchema:
    report = _report_or_404(db, report_id, claims, scope)
    author = _linked_member(member)
    try:
        conversation = add_comment(
            db,
            report.id,
            member_id,
            user_id=claims.sub,
            author_member_id=author.id,
            side=comment_side(claims),
            body=body.body,
        )
    except (MemberNotOnReportError, ConversationRaceError) as exc:
        raise _http_error(exc) from exc
    return _thread_schema(build_thread(db, conversation, claims.sub))


def _comment_or_404(
    db: MembersSessionDep, comment_id: int, claims: AuthClaims, scope: SmallGroupScope
) -> ReportConversationComment:
    comment = get_comment(db, comment_id)
    if comment is None or not scope.includes(comment.conversation.report.small_group_id):
        raise HTTPException(status_code=404, detail=f"Comment with ID {comment_id} not found.")
    conversation_access(comment.conversation.report, claims, scope)
    return comment


@router.patch(
    "/report-conversation-comments/{comment_id}",
    name="edit_report_conversation_comment",
    description="Edit your own comment; the previous text is kept but never returned",
    dependencies=[
        _needs_reports_view,
        Depends(rate_limit("30/minute", scope="edit_report_conversation_comment")),
    ],
)
def patch_report_conversation_comment(
    comment_id: int,
    body: CommentBodySchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ConversationThreadSchema:
    comment = _comment_or_404(db, comment_id, claims, scope)
    _linked_member(member)
    try:
        conversation = edit_comment(db, comment, user_id=claims.sub, body=body.body)
    except (NotYourCommentError, CommentDeletedError) as exc:
        raise _http_error(exc) from exc
    return _thread_schema(build_thread(db, conversation, claims.sub))


@router.delete(
    "/report-conversation-comments/{comment_id}",
    name="delete_report_conversation_comment",
    description="Soft delete your own comment (idempotent); it shows as a stub, its text never returned",
    dependencies=[
        _needs_reports_view,
        Depends(rate_limit("20/minute", scope="delete_report_conversation_comment")),
    ],
)
def delete_report_conversation_comment(
    comment_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ConversationThreadSchema:
    comment = _comment_or_404(db, comment_id, claims, scope)
    _linked_member(member)
    try:
        conversation = delete_comment(db, comment, user_id=claims.sub)
    except NotYourCommentError as exc:
        raise _http_error(exc) from exc
    return _thread_schema(build_thread(db, conversation, claims.sub))


@router.post(
    "/report-conversations/{conversation_id}/resolve",
    name="resolve_report_conversation",
    description="Resolve the thread (idempotent); 409 with the current thread if a newer comment exists",
    dependencies=[_needs_reports_view, Depends(rate_limit("30/minute", scope="resolve_report_conversation"))],
)
def post_report_conversation_resolve(
    conversation_id: int,
    body: ResolveBodySchema,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ConversationThreadSchema:
    conversation = _conversation_or_404(db, conversation_id, claims, scope)
    resolver = _linked_member(member)
    try:
        resolve(
            db,
            conversation,
            user_id=claims.sub,
            member_id=resolver.id,
            last_comment_id=body.last_comment_id,
        )
    except StaleThreadError:
        current = get_conversation(db, conversation_id) or conversation
        raise StaleConversationHTTPError(_thread_schema(build_thread(db, current, claims.sub))) from None
    return _thread_schema(build_thread(db, get_conversation(db, conversation_id) or conversation, claims.sub))


@router.post(
    "/report-conversations/{conversation_id}/reopen",
    name="reopen_report_conversation",
    description="Reopen a resolved thread (idempotent)",
    dependencies=[_needs_reports_view, Depends(rate_limit("30/minute", scope="reopen_report_conversation"))],
)
def post_report_conversation_reopen(
    conversation_id: int,
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    member: CurrentMemberDep,
) -> ConversationThreadSchema:
    conversation = _conversation_or_404(db, conversation_id, claims, scope)
    _linked_member(member)
    reopen(db, conversation)
    return _thread_schema(build_thread(db, get_conversation(db, conversation_id) or conversation, claims.sub))


# "counts" is declared before the inbox so it can never be read as a conversation id.
@router.get(
    "/report-conversations/counts",
    name="count_report_conversations_needing_reply",
    description="How many threads wait for the caller's reply (the sidebar badge); 0 outside the audience",
)
def get_report_conversation_counts(
    db: MembersSessionDep, claims: CurrentClaimsDep, scope: OptionalSmallGroupScopeDep
) -> NeedsMyReplyCountSchema:
    count = count_needing_reply(
        db, group_ids=conversation_group_ids(claims, scope), my_side=comment_side(claims)
    )
    return NeedsMyReplyCountSchema(needs_my_reply=count)


@router.get(
    "/report-conversations",
    name="list_report_conversations_inbox",
    description="The inbox: threads across the groups the caller can see, newest first, with tab counts",
    dependencies=[_needs_reports_view],
)
def get_report_conversation_inbox(
    db: MembersSessionDep,
    claims: CurrentClaimsDep,
    scope: SmallGroupScopeDep,
    tab: InboxTab = "reply",
    small_group_id: Annotated[int | None, Query(alias="smallGroupId")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InboxSchema:
    page = get_inbox(
        db,
        group_ids=conversation_group_ids(claims, scope),
        user_id=claims.sub,
        my_side=comment_side(claims),
        tab=tab,
        small_group_id=small_group_id,
        limit=limit,
        offset=offset,
    )
    return InboxSchema(
        items=[
            InboxItemSchema(
                id=i.id,
                status=i.status,
                needs_my_reply=i.needs_my_reply,
                unread=i.unread,
                member=InboxMemberSchema(id=i.member.member_id, name=i.member.name),
                group=InboxGroupSchema(id=i.group.id, name=i.group.name, closed=i.group.closed),
                report=InboxReportSchema(id=i.report.id, meeting_date=i.report.meeting_date),
                last_comment=InboxLastCommentSchema(
                    author_name=i.last_comment.author_name,
                    mine=i.last_comment.mine,
                    deleted=i.last_comment.deleted,
                    excerpt=i.last_comment.excerpt,
                    created_at=i.last_comment.created_at,
                ),
                resolved_by=ConversationPersonSchema(
                    member_id=i.resolved_by.member_id, name=i.resolved_by.name
                )
                if i.resolved_by is not None
                else None,
                comment_count=i.comment_count,
            )
            for i in page.items
        ],
        counts=InboxCountsSchema(
            reply=page.counts.reply, open=page.counts.open, resolved=page.counts.resolved
        ),
        total=page.total,
    )
