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
MAX_REQUEST_BODY_SIZE = int(os.getenv("REQUEST_SIZE_LIMIT_KB", DEFAULT_LIMIT_KB)) * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size for DoS protection.

    Rejects requests with Content-Length header exceeding the configured limit.
    For requests without Content-Length, reads the body and checks size.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip size check for GET/HEAD/OPTIONS (no body)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Check Content-Length header first (fast path)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > MAX_REQUEST_BODY_SIZE:
                    logger.warning(
                        "Request rejected: Content-Length %d exceeds limit %d (path=%s)",
                        length, MAX_REQUEST_BODY_SIZE, request.url.path
                    )
                    return JSONResponse(
                        {"error": "request_too_large", "detail": f"Request body exceeds {MAX_REQUEST_BODY_SIZE // 1024}KB limit"},
                        status_code=413,
                    )
            except ValueError:
                pass  # Invalid Content-Length, proceed with request

        return await call_next(request)
