from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Discriminator, StringConstraints, Tag

from membership_management.api.schemas.base import CamelModel
from membership_management.api.schemas.person import PersonSchema
from membership_management.data.small_groups.models import ConversationSide, ConversationStatus, ReportSection


class AttendanceAnchorSchema(CamelModel):
    """A thread about one member's attendance row."""

    type: Literal["attendance"] = "attendance"
    member_id: int


class GuestAttendanceAnchorSchema(CamelModel):
    """A thread about one guest's attendance row."""

    type: Literal["attendance"] = "attendance"
    guest_id: int


class SectionAnchorSchema(CamelModel):
    """A thread about one of the report's texts (prayer & follow-up rule 14)."""

    type: Literal["section"] = "section"
    key: ReportSection


def _anchor_kind(value: object) -> str:
    """Discriminator: `type` can't tell a member's attendance anchor from a guest's, so look at the id."""
    if isinstance(value, dict):
        kind, has_guest = value.get("type"), "guestId" in value or "guest_id" in value
    else:
        kind, has_guest = getattr(value, "type", None), hasattr(value, "guest_id")
    if kind == "section":
        return "section"
    return "guest" if has_guest else "member"


# What the thread is about; clients switch on `type`, then on which id is there (`memberId`/`guestId`).
ConversationAnchorSchema = Annotated[
    Annotated[AttendanceAnchorSchema, Tag("member")]
    | Annotated[GuestAttendanceAnchorSchema, Tag("guest")]
    | Annotated[SectionAnchorSchema, Tag("section")],
    Discriminator(_anchor_kind),
]


class ConversationSummarySchema(CamelModel):
    id: int
    anchor: ConversationAnchorSchema
    # Who it's about, a member or a guest; null for a section thread.
    person: PersonSchema | None
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


class InboxMemberSchema(CamelModel):
    id: int
    name: str


class ConversationThreadSchema(CamelModel):
    id: int
    anchor: ConversationAnchorSchema
    # Same shape as the inbox row; the name comes from members, so it is there even when the
    # attendance row is gone. Null for a section thread and for a guest's (`person` has them).
    member: InboxMemberSchema | None
    # Who it's about, a member or a guest; null for a section thread.
    person: PersonSchema | None
    status: ConversationStatus
    resolved_by: ConversationPersonSchema | None
    resolved_at: datetime | None
    first_unread_comment_id: int | None
    comments: list[ConversationCommentSchema]


# Rule 7: plain text, 1-4000 characters after trimming.
CommentBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class CommentBodySchema(CamelModel):
    body: CommentBody


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
    anchor: ConversationAnchorSchema
    # Null for a section thread and for a guest's (`person` has them).
    member: InboxMemberSchema | None
    # Who it's about, a member or a guest; null for a section thread.
    person: PersonSchema | None
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


class ResolveBodySchema(CamelModel):
    """The newest comment the caller saw (null: the thread has no live comments), so a comment posted
    since can't be resolved over unseen. Required, so a client can't skip the check by omission."""

    last_comment_id: int | None
