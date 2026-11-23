"""Report conversations' side of the conversation emails (spec, *Contracts (Part 2: email)*): the event a
new comment writes, and the consumer that turns it into notification requests (audience, recipients,
watchers, unwatch, throttle). Hands its requests to `notifications/`; never reads channel preferences.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from membership_management.data.members.models import Member
from membership_management.data.outbox.models import OutboxEvent
from membership_management.data.small_groups.access_rules import (
    Perms,
    can_read_group_conversations,
    small_group_scope_for,
)
from membership_management.data.small_groups.conversation_queries import (
    conversation_subject_key,
    first_comment_side_query,
    group_leader_user_ids_query,
    participant_user_ids_query,
    watch_opt_out_user_ids_query,
)
from membership_management.data.small_groups.models import (
    ConversationSide,
    ReportConversation,
    ReportConversationComment,
    ReportSection,
)
from membership_management.data.small_groups.queries import led_small_group_ids_by_member_query
from membership_management.notifications.config import notification_settings
from membership_management.notifications.deliveries import NotificationRequest, create_deliveries
from membership_management.notifications.entries import EntryRequest, create_entries

COMMENT_ADDED = "report_conversation.comment_added"
# The notifications/ category: one preference ("Conversation emails") covers every template below.
CATEGORY = "report_conversation"
_TEMPLATE_NEW = "report-conversation.new"
_TEMPLATE_REPLY = "report-conversation.reply"
# auth-server's limit on groupName (trimmed, 1-200); actorName gets the same cut to be safe.
_NAME_LIMIT = 200
# The possible watchers (rule 18): everyone holding what the full-scope observation audience needs. A
# superset by design; `readers_of_group` (the shared rule) decides who really reads each group.
WATCHER_PERMISSIONS = (
    "smallGroups:all",
    "smallGroups:view",
    "smallGroupReports:view",
    "smallGroupReports:viewObservations",
)
# The fast path's head start: the sweep leaves a new event alone this long (the submit event too).
HEAD_START = timedelta(seconds=60)
# One deadline per comment (spec, *Expiry*), and per submit; its deliveries inherit it.
EMAIL_DEADLINE = timedelta(hours=24)

Reason = Literal["leader", "participant", "watcher"]
# Spec, *Recipients*: when someone qualifies twice, the first of these wins.
_REASON_RANK: dict[Reason, int] = {"participant": 0, "leader": 1, "watcher": 2}


def comment_added_event(comment: ReportConversationComment, *, starts_thread: bool) -> OutboxEvent:
    """The outbox row for a new comment (payload v1): ids and facts only, never the text. `occurredAt`
    is the comment's `created_at` exactly, the value the throttle compares with `last_read_at`."""
    occurred_at = comment.created_at
    return OutboxEvent(
        event_type=COMMENT_ADDED,
        schema_version=1,
        aggregate_type="report_conversation",
        aggregate_id=comment.conversation_id,
        payload={
            "conversationId": comment.conversation_id,
            "commentId": comment.id,
            "side": comment.side,
            "authorUserId": comment.author_user_id,
            "startsThread": starts_thread,
            "occurredAt": occurred_at.isoformat(),
        },
        created_at=occurred_at,
        next_attempt_at=occurred_at + HEAD_START,
        expires_at=occurred_at + EMAIL_DEADLINE,
    )


def candidate_user_ids(
    session: Session, payload: Mapping[str, Any], possible_watchers: Collection[str]
) -> frozenset[str]:
    """Everyone this event could email, for the one permissions lookup before its transaction (spec,
    *Candidate snapshot*). A superset: the rules inside the transaction pick from it, and nobody
    outside it can be added there. Empty when the comment is gone or deleted: nothing to look up."""
    comment = session.get(ReportConversationComment, payload["commentId"])
    if comment is None or comment.deleted_at is not None:
        return frozenset()
    users = set(session.scalars(group_leader_user_ids_query(comment.conversation.report.small_group_id)))
    users |= set(session.scalars(participant_user_ids_query(comment.conversation_id)))
    if comment.side == "leaders":
        users |= set(possible_watchers)  # watchers only hear leaders'-side comments (rule 19)
    users.discard(comment.author_user_id)
    return frozenset(users)


def readers_of_group(
    session: Session, perms_by_user: Mapping[str, Perms], small_group_id: int
) -> frozenset[str]:
    """Rule 23: the users who may read this group's conversations, by the API's own rule: each one's
    scope from their linked member (as `get_current_member` resolves it) and `small_group_scope_for`,
    then `can_read_group_conversations`. A user missing from `perms_by_user` is never a reader."""
    if not perms_by_user:
        return frozenset()
    # A comprehension, not dict(result): a Result has .keys() (its columns), so dict() reads it as a mapping.
    member_of: dict[str, int] = {
        user_id: member_id
        for user_id, member_id in session.execute(
            select(Member.user_id, Member.id).where(Member.user_id.in_(list(perms_by_user)))
        )
    }
    led: dict[int, set[int]] = defaultdict(set)
    if member_of:  # nobody linked: no led groups to look up
        for member_id, group_id in session.execute(led_small_group_ids_by_member_query(member_of.values())):
            led[member_id].add(group_id)
    readers = set()
    for user_id, perms in perms_by_user.items():
        member_id = member_of.get(user_id)
        led_ids = frozenset(led[member_id]) if member_id is not None else frozenset()
        scope = small_group_scope_for(perms, led_ids, member_id)
        if can_read_group_conversations(perms, scope, small_group_id):
            readers.add(user_id)
    return frozenset(readers)


def choose_recipients(
    *,
    side: ConversationSide,
    starts_thread: bool,
    author_user_id: str,
    leaders: Collection[str],
    participants: Collection[str],
    watchers: Collection[str],
    opted_out: Collection[str],
    readers: Collection[str],
) -> dict[str, Reason]:
    """Who hears about a comment, and why (spec, *Recipients*). Elders' side → the group's leaders;
    leaders' side → its watchers, minus those who unwatched it (as watchers only, rule 21); a reply also
    → everyone else who commented. Never the author; only readers of the group (rule 23)."""
    wanted: list[tuple[str, Reason]] = []
    if not starts_thread:
        wanted += [(u, "participant") for u in participants]
    if side == "elders":
        wanted += [(u, "leader") for u in leaders]
    else:
        wanted += [(u, "watcher") for u in watchers if u not in opted_out]
    chosen: dict[str, Reason] = {}
    for user_id, reason in wanted:
        if user_id == author_user_id or user_id not in readers:
            continue
        if user_id not in chosen or _REASON_RANK[reason] < _REASON_RANK[chosen[user_id]]:
            chosen[user_id] = reason
    return chosen


# Rule 20, the spec's statement as written (*Recipients*, *Throttle, atomic*).
_THROTTLE = text("""
    INSERT INTO report_conversation_notify_state AS s (user_id, conversation_id, last_notified_at)
    SELECT u, :conversation_id, :occurred_at
    FROM unnest(CAST(:user_ids AS varchar[])) AS u
    WHERE coalesce((SELECT r.last_read_at FROM report_conversation_reads r
                    WHERE r.user_id = u AND r.conversation_id = :conversation_id),
                   '-infinity') < :occurred_at
    ORDER BY u
    ON CONFLICT (user_id, conversation_id) DO UPDATE SET last_notified_at = excluded.last_notified_at
    WHERE s.last_notified_at
          <= coalesce((SELECT r.last_read_at FROM report_conversation_reads r
                       WHERE r.user_id = s.user_id AND r.conversation_id = s.conversation_id),
                      '-infinity')
    RETURNING user_id
""")


def pass_throttle(
    session: Session, conversation_id: int, user_ids: Collection[str], occurred_at: datetime
) -> frozenset[str]:
    """Rule 20: the users who may get an email about this comment, claimed atomically. One statement
    for all of them, sorted, so two events in one conversation lock rows in the same order."""
    if not user_ids:
        return frozenset()
    result = session.execute(
        _THROTTLE,
        {"conversation_id": conversation_id, "occurred_at": occurred_at, "user_ids": sorted(user_ids)},
    )
    return frozenset(result.scalars())


def thread_path_and_topic(conversation: ReportConversation) -> tuple[str, str]:
    """The email's deep link and `topic`, by the thread's anchor: a section, a guest's row or a
    member's row (the three shapes auth-server accepts)."""
    base = f"/groups/reports/{conversation.report_id}"
    if conversation.section is not None:
        section = ReportSection(conversation.section).value
        return f"{base}?section={section}", section
    if conversation.guest_id is not None:
        return f"{base}?guest={conversation.guest_id}", "person"
    return f"{base}?person={conversation.member_id}", "person"


def process_comment_added(
    session: Session,
    event: OutboxEvent,
    perms_by_user: Mapping[str, Perms],
    possible_watchers: Collection[str],
) -> int:
    """The consumer, inside the event's transaction (after its fence): who hears about the comment, and
    what they're sent, handed to `notifications/`. `perms_by_user` is the pinned snapshot for this
    event's candidates (`candidate_user_ids`): anyone missing from it can't read, so nobody is added
    here. A comment gone or deleted by now gives nothing. Returns the deliveries created."""
    payload = event.payload
    comment = session.get(ReportConversationComment, payload["commentId"])
    if comment is None or comment.deleted_at is not None:
        return 0
    conversation = comment.conversation
    report = conversation.report
    group_id = report.small_group_id
    watchers = set(possible_watchers) if comment.side == "leaders" else set()
    opted_out = set(session.scalars(watch_opt_out_user_ids_query(group_id, watchers))) if watchers else set()
    chosen = choose_recipients(
        side=comment.side,
        starts_thread=payload["startsThread"],
        author_user_id=comment.author_user_id,
        leaders=set(session.scalars(group_leader_user_ids_query(group_id))),
        participants=set(session.scalars(participant_user_ids_query(conversation.id))),
        watchers=watchers,
        opted_out=opted_out,
        readers=readers_of_group(session, perms_by_user, group_id),
    )
    allowed = pass_throttle(session, conversation.id, chosen, datetime.fromisoformat(payload["occurredAt"]))
    if not allowed:
        return 0
    path, topic = thread_path_and_topic(conversation)
    template = _TEMPLATE_NEW if payload["startsThread"] else _TEMPLATE_REPLY
    first_side = session.scalar(first_comment_side_query(conversation.id))
    started_by = "elders" if first_side == "elders" else "leaders"
    common = {
        "actorName": comment.author.name.strip()[:_NAME_LIMIT],
        "groupName": report.small_group.name.strip()[:_NAME_LIMIT],
        "meetingDate": report.meeting_date.isoformat(),
        "topic": topic,
        "startedBy": started_by,
    }
    data_by_user = {user_id: {**common, "reason": chosen[user_id]} for user_id in sorted(allowed)}
    # The in-app entry (notifications spec, rule 5): the same recipients, before any email preference.
    if (
        notification_settings.in_app_notifications_enabled
        and notification_settings.conversation_emails_enabled
    ):
        create_entries(
            session,
            event.id,
            [
                EntryRequest(
                    user_id=user_id,
                    category=CATEGORY,
                    template=template,
                    data=data,
                    path=path,
                    subject_key=conversation_subject_key(conversation.id),
                )
                for user_id, data in data_by_user.items()
            ],
        )
    requests = [
        NotificationRequest(
            recipient_user_id=user_id,
            category=CATEGORY,
            channel="email",
            template=template,
            payload={"recipientUserId": user_id, "template": template, "data": data, "path": path},
            not_after=event.expires_at,
        )
        for user_id, data in data_by_user.items()
    ]
    return create_deliveries(session, event.id, requests)
