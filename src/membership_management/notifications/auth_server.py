"""The calls to auth-server's /internal/* routes (its REPORT-CONVERSATIONS-EMAIL-HANDOFF.md, as built):
the two user lookups the worker needs before processing, and the Sender. Every call sends
X-Internal-Token. Never logs a payload, an address or the token: only status codes and error codes."""

import json
import logging
import threading
from collections.abc import Collection, Mapping, Sequence
from typing import Any

import httpx

from membership_management.data.small_groups.access_rules import Perms
from membership_management.notifications.config import notification_settings
from membership_management.notifications.sender import SendOutcome

logger = logging.getLogger(__name__)

# Lease rule (spec): lease > batch x timeout + margin = 2 min > 10 x 5 s + margin.
TIMEOUT_SECONDS = 5.0
# POST /internal/users/permissions takes at most this many ids per call.
PERMISSIONS_CHUNK = 500

_client: httpx.Client | None = None
# The API calls this from several threads at once (fast paths in the thread pool, the embedded worker):
# without the lock, two first calls could each build a client and one would leak.
_client_lock = threading.Lock()


class AuthServerUnavailable(Exception):  # noqa: N818 (a condition, not a bug: the name reads better)
    """A lookup failed (network, timeout, any non-2xx). Transient for everything that needed it: the
    worker claims nothing / processes nothing on partial data. `args[0]` is a short reason."""


def _http() -> httpx.Client:
    """One client for the process (keeps connections to auth-server open), made on first use."""
    global _client
    client = _client
    if client is not None:  # the common case, no lock
        return client
    with _client_lock:
        if _client is None:  # checked again: another thread may have made it while we waited
            token = notification_settings.internal_api_token
            if token is None:  # settings refuse this while emails are on
                raise RuntimeError("INTERNAL_API_TOKEN is not set")
            _client = httpx.Client(
                base_url=notification_settings.auth_server_url,
                timeout=TIMEOUT_SECONDS,
                headers={"X-Internal-Token": token.get_secret_value(), "Content-Type": "application/json"},
            )
        return _client


def close() -> None:
    """For shutdown: the worker's, or the API's (embedded worker or not; the fast path opens it too)."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def _body(data: Mapping[str, Any]) -> bytes:
    # ASCII-escaped JSON, not httpx's json= (raw UTF-8): auth-server's Stage 3 notes expect it.
    return json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _error_code(response: httpx.Response) -> str | None:
    """auth-server's `{ code, message }`; None for a bare error (e.g. route not deployed)."""
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _reason(response: httpx.Response) -> str:
    code = _error_code(response)
    return f"{response.status_code} {code}" if code else str(response.status_code)


def _get_json(response: httpx.Response, what: str) -> Any:  # noqa: ANN401 (JSON)
    if not response.is_success:
        reason = _reason(response)
        # A 4xx here is a bug or misconfiguration (token, deploy order, permission name), not an outage.
        log = logger.error if response.status_code < 500 else logger.warning
        log("auth-server %s failed: %s", what, reason)
        raise AuthServerUnavailable(reason)
    return response.json()


def users_with_permissions(permissions: Sequence[str]) -> list[str]:
    """GET /internal/users/with-permission: users holding all of them ("resource:action"), banned left
    out. Used only for the possible watchers, a superset the shared read check narrows."""
    try:
        response = _http().get(
            "/internal/users/with-permission", params=[("permission", p) for p in permissions]
        )
    except httpx.HTTPError as exc:
        logger.warning("auth-server with-permission failed: %s", type(exc).__name__)
        raise AuthServerUnavailable(type(exc).__name__) from exc
    return list(_get_json(response, "with-permission")["userIds"])


def permissions_for(user_ids: Collection[str]) -> dict[str, Perms]:
    """POST /internal/users/permissions in chunks of 500, merged: each user's perms in the JWT's shape.
    Unknown and banned users are absent (they can't read). Any failed chunk fails the whole lookup,
    so nothing is processed on partial data."""
    ids = sorted(set(user_ids))
    merged: dict[str, Perms] = {}
    for start in range(0, len(ids), PERMISSIONS_CHUNK):
        chunk = ids[start : start + PERMISSIONS_CHUNK]
        try:
            response = _http().post("/internal/users/permissions", content=_body({"userIds": chunk}))
        except httpx.HTTPError as exc:
            logger.warning("auth-server permissions failed: %s", type(exc).__name__)
            raise AuthServerUnavailable(type(exc).__name__) from exc
        merged.update(_get_json(response, "permissions")["users"])
    return merged


def _send_outcome(response: httpx.Response) -> SendOutcome:
    """The spec's status-code table, plus what auth-server built (handoff, *Sender outcome table*)."""
    status = response.status_code
    if response.is_success:
        return SendOutcome("sent")
    code = _error_code(response)
    reason = _reason(response)
    if status == 410 or (status == 404 and code == "recipient_unavailable"):
        return SendOutcome("dead", reason)  # recipient gone, banned or unverified
    if status == 404:
        logger.error("auth-server notifications: bare 404 (route not deployed or wrong base URL)")
        return SendOutcome("transient", reason)
    if status in (401, 403):
        logger.error("auth-server notifications: %s (internal token wrong or rotated)", reason)
        return SendOutcome("transient", reason)
    if status in (408, 429) or status >= 500:
        log = logger.error if code in ("internal_api_disabled", "internal_error") else logger.warning
        log("auth-server notifications: %s", reason)
        return SendOutcome("transient", reason)
    # 409 idempotency_conflict, 422 invalid_request / unknown_template / invalid_data, or any other 4xx:
    # the services disagree or our payload is wrong. Retrying the same payload can't help.
    logger.error("auth-server notifications rejected the delivery: %s", reason)
    return SendOutcome("dead", reason)


class AuthServerSender:
    """The Sender: POST /internal/notifications with the delivery's payload and its idempotency key."""

    def send(self, payload: Mapping[str, Any], idempotency_key: str) -> SendOutcome:
        try:
            response = _http().post(
                "/internal/notifications", content=_body({"idempotencyKey": idempotency_key, **payload})
            )
        except httpx.HTTPError as exc:  # timeout, connection refused, protocol error
            logger.warning("auth-server notifications failed: %s", type(exc).__name__)
            return SendOutcome("transient", type(exc).__name__)
        return _send_outcome(response)
