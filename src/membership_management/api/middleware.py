import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s %s -> %s (%.1fms)",
            request.client.host if request.client else "-",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, timeout_seconds: float) -> None:
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout_seconds)
        except TimeoutError:
            logger.warning(
                "Request timed out after %.1fs: %s %s",
                self.timeout_seconds,
                request.method,
                request.url.path,
            )
            return JSONResponse({"detail": "Request timed out"}, status_code=504)
