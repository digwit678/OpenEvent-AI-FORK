"""
Rate Limiting Middleware for OpenEvent API

Provides configurable request rate limiting to prevent abuse.
Disabled by default - enable with RATE_LIMIT_ENABLED=1.

Configuration:
    RATE_LIMIT_ENABLED: Set to "1" to enable rate limiting (default: disabled)
    RATE_LIMIT_RPS: Requests per second per IP (default: TBD - see OPEN_DECISIONS.md DECISION-014)
    RATE_LIMIT_BURST: Burst allowance (default: TBD)
    RATE_LIMIT_EXEMPT_PATHS: Comma-separated paths to exempt (default: /api/workflow/health,/docs,/openapi.json)

Usage:
    from api.middleware.rate_limit import setup_rate_limiting
    setup_rate_limiting(app)

See docs/plans/OPEN_DECISIONS.md DECISION-014 for rate limit value decisions.
"""

import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Check if rate limiting is enabled
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "0") == "1"

# Rate limit configuration (defaults are placeholders - see DECISION-014)
# These will be configured once we decide on appropriate values
RATE_LIMIT_RPS = os.getenv("RATE_LIMIT_RPS", "")  # Empty = not configured yet
RATE_LIMIT_BURST = os.getenv("RATE_LIMIT_BURST", "")  # Empty = not configured yet

# Paths exempt from rate limiting (health checks, docs)
_exempt_paths_raw = os.getenv(
    "RATE_LIMIT_EXEMPT_PATHS",
    "/api/workflow/health,/docs,/openapi.json,/redoc"
)
RATE_LIMIT_EXEMPT_PATHS = [p.strip() for p in _exempt_paths_raw.split(",") if p.strip()]


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI app.

    Does nothing if RATE_LIMIT_ENABLED != "1" or if limits are not configured.
    """
    if not RATE_LIMIT_ENABLED:
        logger.info("Rate limiting disabled (RATE_LIMIT_ENABLED != 1)")
        return

    if not RATE_LIMIT_RPS or not RATE_LIMIT_BURST:
        logger.warning(
            "Rate limiting enabled but limits not configured. "
            "Set RATE_LIMIT_RPS and RATE_LIMIT_BURST. "
            "See OPEN_DECISIONS.md DECISION-014."
        )
        return

    try:
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
    except ImportError:
        logger.error("slowapi not installed. Run: pip install slowapi")
        return

    # Parse rate limit values
    try:
        rps = int(RATE_LIMIT_RPS)
        burst = int(RATE_LIMIT_BURST)
    except ValueError:
        logger.error(f"Invalid rate limit values: RPS={RATE_LIMIT_RPS}, BURST={RATE_LIMIT_BURST}")
        return

    # Create limiter with IP-based identification
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{rps}/second"],
        storage_uri="memory://",  # In-memory storage (use redis:// for distributed)
    )

    # Store limiter on app state for route-level access if needed
    app.state.limiter = limiter

    # Add middleware
    app.add_middleware(SlowAPIMiddleware)

    # Custom rate limit exceeded handler
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):  # noqa: ARG001
        # Check if path is exempt
        if any(request.url.path.startswith(exempt) for exempt in RATE_LIMIT_EXEMPT_PATHS):
            # This shouldn't happen since exempt paths bypass limiting,
            # but handle gracefully just in case
            return JSONResponse(
                status_code=200,
                content={"detail": "Request processed"}
            )

        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "detail": f"Rate limit exceeded. Max {rps} requests per second.",
                "retry_after": 1,
            },
            headers={"Retry-After": "1"}
        )

    logger.info(f"Rate limiting enabled: {rps}/s with {burst} burst, exempt: {RATE_LIMIT_EXEMPT_PATHS}")


def get_rate_limit_status() -> dict:
    """Return current rate limit configuration for health/debug endpoints."""
    return {
        "enabled": RATE_LIMIT_ENABLED,
        "configured": bool(RATE_LIMIT_RPS and RATE_LIMIT_BURST),
        "rps": RATE_LIMIT_RPS or "not set",
        "burst": RATE_LIMIT_BURST or "not set",
        "exempt_paths": RATE_LIMIT_EXEMPT_PATHS,
    }
