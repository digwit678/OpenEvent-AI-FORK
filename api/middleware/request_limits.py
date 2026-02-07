"""
Request size limiting middleware for DoS protection.

Limits:
  - MAX_REQUEST_BODY_SIZE: Maximum size of request body (default 1MB)
  - Configurable via REQUEST_SIZE_LIMIT_KB environment variable

Environment Variables:
  - REQUEST_SIZE_LIMIT_KB: Max request body size in KB (default: 1024 = 1MB)
"""

from __future__ import annotations

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Default 1MB, configurable via env var
DEFAULT_LIMIT_KB = 1024
MAX_REQUEST_BODY_SIZE = DEFAULT_LIMIT_KB * 1024


def _get_request_limit_bytes() -> int:
    """Resolve request size limit from env with safe fallback."""
    raw_limit = str(os.getenv("REQUEST_SIZE_LIMIT_KB", DEFAULT_LIMIT_KB)).strip()
    try:
        limit_kb = int(raw_limit)
        if limit_kb <= 0:
            raise ValueError("must be positive")
        return limit_kb * 1024
    except (TypeError, ValueError):
        logger.warning(
            "Invalid REQUEST_SIZE_LIMIT_KB=%r, falling back to default %dKB",
            raw_limit,
            DEFAULT_LIMIT_KB,
        )
        return DEFAULT_LIMIT_KB * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size for DoS protection.

    Rejects requests with Content-Length header exceeding the configured limit.
    For requests without Content-Length, reads the body and checks size.
    """

    async def dispatch(self, request: Request, call_next):
        max_request_body_size = _get_request_limit_bytes()

        # Skip size check for GET/HEAD/OPTIONS (no body)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Check Content-Length header first (fast path)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > max_request_body_size:
                    logger.warning(
                        "Request rejected: Content-Length %d exceeds limit %d (path=%s)",
                        length, max_request_body_size, request.url.path
                    )
                    return JSONResponse(
                        {"error": "request_too_large", "detail": f"Request body exceeds {max_request_body_size // 1024}KB limit"},
                        status_code=413,
                    )
            except ValueError:
                # Invalid Content-Length, fall through to real body-size check.
                pass

        # Fallback path: enforce limit even when Content-Length is missing/invalid.
        # We replay the buffered body so downstream handlers can still read it.
        body = await request.body()
        if len(body) > max_request_body_size:
            logger.warning(
                "Request rejected: body size %d exceeds limit %d (path=%s)",
                len(body), max_request_body_size, request.url.path
            )
            return JSONResponse(
                {"error": "request_too_large", "detail": f"Request body exceeds {max_request_body_size // 1024}KB limit"},
                status_code=413,
            )

        async def _receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]

        return await call_next(request)
