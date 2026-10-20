from fastapi import APIRouter, Depends, HTTPException, Response, status

from membership_management.api.access import (
    SmallGroupScope,
    SmallGroupScopeDep,
    comment_side,
    conversation_access,
)
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
    ConversationAnchorSchema,
    ConversationCommentSchema,
    ConversationCountsSchema,
    ConversationPersonSchema,
    ConversationSummarySchema,
    ConversationThreadSchema,
    ReportConversationsSchema,
)
from membership_management.data.small_groups.conversation_services import (
    ConversationNotFoundError,
    MemberNotOnReportError,
    build_thread,
    get_conversation,
    get_report_conversations,
    get_report_member_conversation,
    mark_read,
)
from membership_management.data.small_groups.models import SmallGroupReport
from membership_management.data.small_groups.results import ConversationThread
from membership_management.data.small_groups.services import get_report

# No prefix: the routes live under both /small-group-reports/{id}/... and /report-conversations.
# Everyone in the report's observation audience can use them (no new permission, spec rule 4):
# `smallGroupReports: view` gets you in, `conversation_access` decides per report.
router = APIRouter(
    tags=["report-conversations"],
    dependencies=[
        Depends(get_current_claims),
        Depends(default_user_rate_limit),
        Depends(require_permission("smallGroupReports", "view")),
    ],
)


def _http_error(exc: Exception) -> HTTPException:
    """Map a conversation domain error to its HTTP error (the staff app matches on status and `detail`)."""
    if isinstance(exc, MemberNotOnReportError):
        return HTTPException(status_code=422, detail="That person has no attendance row on this report.")
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=404, detail="No conversation yet.")
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


def _thread_schema(thread: ConversationThread) -> ConversationThreadSchema:
    return ConversationThreadSchema(
        id=thread.id,
        anchor=ConversationAnchorSchema(member_id=thread.member_id),
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
    dependencies=[Depends(rate_limit("120/minute", scope="mark_report_conversation_read"))],
)
def post_report_conversation_read(
    conversation_id: int, db: MembersSessionDep, claims: CurrentClaimsDep, scope: SmallGroupScopeDep
) -> Response:
    conversation = get_conversation(db, conversation_id)
    if conversation is None or not scope.includes(conversation.report.small_group_id):
        raise HTTPException(status_code=404, detail=f"Conversation with ID {conversation_id} not found.")
    conversation_access(conversation.report, claims, scope)
    mark_read(db, conversation.id, claims.sub)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
