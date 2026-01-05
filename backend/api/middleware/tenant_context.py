"""
Request-scoped tenant context middleware.

Enables per-request tenant switching via headers in test/dev environments.
This is the infrastructure layer for multi-tenancy - nothing acts on
these values until Phase 2 integrates them with config.py and adapters.

Headers (only parsed when TENANT_HEADER_ENABLED=1):
  - X-Team-Id: Team/venue UUID or slug (validated format)
  - X-Manager-Id: Manager/actor UUID (validated format)

Security:
  - Headers only accepted when TENANT_HEADER_ENABLED=1 (never in prod)
  - IDs are validated to prevent path traversal attacks
"""

from __future__ import annotations

import os
import re
import logging
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

# Request-scoped tenant context
CURRENT_TEAM_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_TEAM_ID", default=None)
CURRENT_MANAGER_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_MANAGER_ID", default=None)

# Valid ID patterns (UUID or slug format, no path chars)
# UUID: 8-4-4-4-12 hex chars
# Slug: lowercase letters, numbers, hyphens (e.g., "team-alex", "venue-123")
_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}[a-z0-9]?$", re.I)


def _is_valid_id(value: str) -> bool:
    """
    Validate that an ID is safe to use in file paths.

    Accepts:
      - UUIDs (e.g., "550e8400-e29b-41d4-a716-446655440000")
      - Slugs (e.g., "team-alex", "venue-123")

    Rejects:
      - Empty strings
      - Path traversal attempts ("../", "..\\")
      - Special chars that could be dangerous in paths
    """
    if not value or len(value) > 64:
        return False

    # Reject path traversal attempts
    if ".." in value or "/" in value or "\\" in value:
        return False

    # Must match UUID or slug pattern
    return bool(_UUID_PATTERN.match(value) or _SLUG_PATTERN.match(value))


def get_request_team_id() -> Optional[str]:
    """Get team_id from current request context, or None if not set."""
    return CURRENT_TEAM_ID.get()


def get_request_manager_id() -> Optional[str]:
    """Get manager_id from current request context, or None if not set."""
    return CURRENT_MANAGER_ID.get()


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract tenant context from request headers.

    Only active when TENANT_HEADER_ENABLED=1 (test/dev environments).
    In production, tenant context comes from authenticated identity (JWT claims).

    Security: IDs are validated before being accepted to prevent path traversal.
    """

    async def dispatch(self, request: Request, call_next):
        # Only allow header overrides in explicitly enabled environments
        # NEVER enable this in production (TENANT_HEADER_ENABLED should be 0)
        if os.getenv("TENANT_HEADER_ENABLED", "0") == "1":
            team_id = request.headers.get("X-Team-Id")
            manager_id = request.headers.get("X-Manager-Id")

            # Validate and set team_id
            if team_id:
                if _is_valid_id(team_id):
                    CURRENT_TEAM_ID.set(team_id)
                    logger.debug("Set team_id=%s for request %s", team_id, request.url.path)
                else:
                    logger.warning(
                        "Rejected invalid X-Team-Id: %s (path: %s)",
                        team_id[:20] + "..." if len(team_id) > 20 else team_id,
                        request.url.path,
                    )

            # Validate and set manager_id
            if manager_id:
                if _is_valid_id(manager_id):
                    CURRENT_MANAGER_ID.set(manager_id)
                    logger.debug("Set manager_id=%s for request %s", manager_id, request.url.path)
                else:
                    logger.warning(
                        "Rejected invalid X-Manager-Id: %s (path: %s)",
                        manager_id[:20] + "..." if len(manager_id) > 20 else manager_id,
                        request.url.path,
                    )

        response = await call_next(request)
        return response
