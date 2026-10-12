import math
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Response
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

from membership_management.api.config import api_settings
from membership_management.api.jwt_auth import CurrentClaimsDep

if TYPE_CHECKING:
    from limits.limits import RateLimitItem

# --- Per-user rate limiting on the verified JWT `sub` ---
#
# Layering note: this only ever sees requests that already passed JWT verification, so it is the
# *application* layer -- fairness and abuse control per authenticated user. It deliberately does
# NOT limit anonymous traffic by IP; floods and brute-force against unauthenticated endpoints belong
# at the edge (Cloudflare rate-limit rule, AWS WAF rate-based rule on the ALB -- see
# DEPLOYMENT-ROADMAP Phase 8.5). REVISIT before exposing this API publicly (e.g. for a mobile app):
# a per-IP layer becomes necessary then, and a client IP is only trustworthy once the origin
# accepts traffic solely from Cloudflare (CF-Connecting-IP).
#
# Storage comes from RATE_LIMIT_STORAGE_URI, so moving from per-process memory to a shared Redis
# is configuration, not code. With the default memory:// store, counters live in this process only:
# with ApiSettings.workers > 1, or multiple replicas, each process keeps its own, so a limit like
# "60/minute" effectively becomes "60 x (workers x replicas) per minute". Fine at 1 worker / 1
# replica; switch to a shared store before relying on this as a real global guarantee.
#
# Moving-window is the exact algorithm (no burst at window edges, unlike fixed-window) and at
# 10-60 hits per user per window its memory cost is negligible; swap the strategy class here if a
# much larger limit ever makes that cost matter.
_storage = storage_from_string(api_settings.rate_limit_storage_uri)
_strategy = MovingWindowRateLimiter(_storage)


def rate_limit(spec: str, *, scope: str) -> Callable[..., None]:
    """Build a FastAPI dependency limiting each authenticated user to `spec` (e.g. "10/minute").

    `scope` names the bucket, so different limits don't share a counter (a user's "approve" hits
    don't consume their "default" allowance). Depends on CurrentClaimsDep, so it always runs after
    JWT verification and keys on the verified `sub`, never on anything the client merely claims.
    """
    item: RateLimitItem = parse(spec)

    def enforce(claims: CurrentClaimsDep, response: Response) -> None:
        # hit() is the atomic decision (check-and-consume in one storage operation); the stats
        # below are only for the response headers, so a tiny race between the two calls can make a
        # header slightly stale but can never let an over-limit request through.

        allowed = _strategy.hit(item, scope, claims.sub)
        stats = _strategy.get_window_stats(item, scope, claims.sub)

        # Moving window: reset_time is when the oldest hit in the window expires, i.e. when the next
        # slot frees up -- exactly what a rejected client should wait for.
        reset_in = max(1, math.ceil(stats.reset_time - time.time()))
        headers = {
            "RateLimit-Limit": str(item.amount),
            "RateLimit-Remaining": str(stats.remaining),
            "RateLimit-Reset": str(reset_in),
        }
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={**headers, "Retry-After": str(reset_in)},
            )
        response.headers.update(headers)

    return enforce


# The router-wide default: every authenticated user shares this one bucket (scope "default")
# across *all* routes, so it caps their total request rate, while route-specific limits (e.g. the
# approve/reject ones) add stricter caps on top. Built once here so every router uses the same
# callable and therefore the same bucket.
default_user_rate_limit = rate_limit(api_settings.default_rate_limit, scope="default")
