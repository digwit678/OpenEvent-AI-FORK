"""
Rate limiting middleware for API protection.

Configurable limits per endpoint type to prevent abuse and cost spikes.

Environment Variables:
    RATE_LIMIT_ENABLED: Set to "0" to disable (default: "1" in prod, "0" in dev)
    RATE_LIMIT_CONVERSATION: Requests/minute for /api/start-conversation (default: 30)
    RATE_LIMIT_MESSAGE: Requests/minute for /api/send-message (default: 60)
    RATE_LIMIT_DEFAULT: Requests/minute for other endpoints (default: 200)
"""

from __future__ import annotations

import os
import logging
from typing import Callable

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Check if we're in dev mode
_IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")

# Rate limiting disabled by default in dev, enabled in prod
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "0" if _IS_DEV else "1") == "1"

# Configurable limits (requests per minute)
RATE_LIMIT_CONVERSATION = int(os.getenv("RATE_LIMIT_CONVERSATION", "30"))  # Start conversation
RATE_LIMIT_MESSAGE = int(os.getenv("RATE_LIMIT_MESSAGE", "60"))  # Send message
RATE_LIMIT_DEFAULT = int(os.getenv("RATE_LIMIT_DEFAULT", "200"))  # Other endpoints


def get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For for proxied requests."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_client_ip,
    enabled=RATE_LIMIT_ENABLED,
    default_limits=[f"{RATE_LIMIT_DEFAULT}/minute"],
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Handle rate limit exceeded errors."""
    logger.warning(
        "[RateLimit] Exceeded for %s on %s: %s",
        get_client_ip(request),
        request.url.path,
        str(exc),
    )
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please slow down.",
            "retry_after": exc.retry_after if hasattr(exc, "retry_after") else 60,
        },
    )


# Rate limit decorators for specific endpoints
def limit_conversation(func: Callable) -> Callable:
    """Apply conversation rate limit (stricter - costs more)."""
    return limiter.limit(f"{RATE_LIMIT_CONVERSATION}/minute")(func)


def limit_message(func: Callable) -> Callable:
    """Apply message rate limit."""
    return limiter.limit(f"{RATE_LIMIT_MESSAGE}/minute")(func)


def limit_default(func: Callable) -> Callable:
    """Apply default rate limit."""
    return limiter.limit(f"{RATE_LIMIT_DEFAULT}/minute")(func)


def get_rate_limit_status() -> dict:
    """Get current rate limit configuration for admin/debug."""
    return {
        "enabled": RATE_LIMIT_ENABLED,
        "limits": {
            "conversation": f"{RATE_LIMIT_CONVERSATION}/minute",
            "message": f"{RATE_LIMIT_MESSAGE}/minute",
            "default": f"{RATE_LIMIT_DEFAULT}/minute",
        },
        "mode": "production" if not _IS_DEV else "development",
    }
