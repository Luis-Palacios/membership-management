from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import StringConstraints

from membership_management.api.schemas.base import CamelModel
from membership_management.data.small_groups.models import ConversationSide, ConversationStatus


class ConversationAnchorSchema(CamelModel):
    """What the thread is about. Only attendance rows in v1; sections can be added without a client change."""

    type: Literal["attendance"] = "attendance"
    member_id: int


class ConversationSummarySchema(CamelModel):
    id: int
    anchor: ConversationAnchorSchema
    status: ConversationStatus
    comment_count: int
    unread: bool
    needs_my_reply: bool
    last_comment_at: datetime


class ConversationCountsSchema(CamelModel):
    total: int
    needs_my_reply: int


class ReportConversationsSchema(CamelModel):
    conversations: list[ConversationSummarySchema]
    counts: ConversationCountsSchema


class ConversationPersonSchema(CamelModel):
    member_id: int
    name: str


class CommentAuthorSchema(CamelModel):
    member_id: int
    name: str
    side: ConversationSide


class ConversationCommentSchema(CamelModel):
    id: int
    author: CommentAuthorSchema
    # null when deleted: the stored text is never returned again.
    body: str | None
    created_at: datetime
    edited_at: datetime | None
    deleted: bool
    mine: bool


class ConversationThreadSchema(CamelModel):
    id: int
    anchor: ConversationAnchorSchema
    status: ConversationStatus
    resolved_by: ConversationPersonSchema | None
    resolved_at: datetime | None
    first_unread_comment_id: int | None
    comments: list[ConversationCommentSchema]


# Rule 7: plain text, 1-4000 characters after trimming.
CommentBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class CommentBodySchema(CamelModel):
    body: CommentBody


class InboxMemberSchema(CamelModel):
    id: int
    name: str


class InboxGroupSchema(CamelModel):
    id: int
    name: str
    closed: bool


class InboxReportSchema(CamelModel):
    id: int
    meeting_date: date


class InboxLastCommentSchema(CamelModel):
    author_name: str
    mine: bool
    deleted: bool
    # First 160 characters of the newest non-deleted comment; null when every comment is deleted.
    excerpt: str | None
    created_at: datetime


class InboxItemSchema(CamelModel):
    id: int
    status: ConversationStatus
    needs_my_reply: bool
    unread: bool
    member: InboxMemberSchema
    group: InboxGroupSchema
    report: InboxReportSchema
    last_comment: InboxLastCommentSchema
    resolved_by: ConversationPersonSchema | None
    comment_count: int


class InboxCountsSchema(CamelModel):
    reply: int
    open: int
    resolved: int


class InboxSchema(CamelModel):
    items: list[InboxItemSchema]
    counts: InboxCountsSchema
    total: int


class NeedsMyReplyCountSchema(CamelModel):
    needs_my_reply: int
