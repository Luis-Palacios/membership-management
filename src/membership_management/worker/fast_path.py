"""The best-effort fast path (spec, *The worker*): right after a comment's response, process that one
event and send its deliveries, with its own DB sessions and through the same claim code as the sweep
(so they never race). Nothing depends on it: if it fails or never runs, the sweep picks the event up
after its 60 s head start."""

import logging

from membership_management.data.database import MembershipSessionLocal
from membership_management.data.small_groups.conversation_notifications import WATCHER_PERMISSIONS
from membership_management.notifications.auth_server import (
    AuthServerSender,
    AuthServerUnavailable,
    users_with_permissions,
)
from membership_management.notifications.sending import send_due_deliveries
from membership_management.worker.events import process_due_events

logger = logging.getLogger(__name__)


def run_fast_path(event_id: int) -> None:
    """A plain `def`: Starlette runs it in the thread pool after the response is sent. Every exception
    is caught here, since one raised in a background task is otherwise only half-visible."""
    try:
        try:
            # No sweep cache here: fetched for this one event, before claiming it.
            watchers = users_with_permissions(WATCHER_PERMISSIONS)
        except AuthServerUnavailable:
            return  # nothing claimed; the sweep retries after the head start
        process_due_events(MembershipSessionLocal, watchers, event_id=event_id)
        send_due_deliveries(MembershipSessionLocal, AuthServerSender(), source_event_id=event_id)
    except Exception:
        logger.exception("conversation email fast path failed for outbox event %s", event_id)
