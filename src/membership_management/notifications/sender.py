"""What `notifications/` needs from whatever sends a delivery. Today the only implementation is
auth-server (`auth_server.AuthServerSender`); a notification service later is another one."""

from collections.abc import Mapping
from typing import Any, Literal, NamedTuple, Protocol

# sent: done. dead: permanent, never retried. transient: dependency trouble, retried until the expiry
# (spec, *Failures and retries*).
SendStatus = Literal["sent", "dead", "transient"]


class SendOutcome(NamedTuple):
    status: SendStatus
    # Short, for `last_error`: a status code, an error `code` or an exception class. Never PII.
    error: str | None = None


class Sender(Protocol):
    def send(self, payload: Mapping[str, Any], idempotency_key: str) -> SendOutcome:
        """Send one delivery's payload. Never raises for an HTTP or network failure: those are
        outcomes. The same key must always come with the same payload."""
        ...
