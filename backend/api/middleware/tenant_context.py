"""
Request-scoped tenant context middleware.

Enables per-request tenant switching via headers in test/dev environments.
This is the infrastructure layer for multi-tenancy - nothing acts on
these values until Phase 2 integrates them with config.py and adapters.

Headers (only parsed when TENANT_HEADER_ENABLED=1):
  - X-Team-Id: Team/venue UUID
  - X-Manager-Id: Manager/actor UUID
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Request-scoped tenant context
CURRENT_TEAM_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_TEAM_ID", default=None)
CURRENT_MANAGER_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_MANAGER_ID", default=None)


def get_request_team_id() -> Optional[str]:
    """Get team_id from current request context, or None if not set."""
    return CURRENT_TEAM_ID.get()


def get_request_manager_id() -> Optional[str]:
    """Get manager_id from current request context, or None if not set."""
    return CURRENT_MANAGER_ID.get()


import logging

logger = logging.getLogger(__name__)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract tenant context from request headers.

    Only active when TENANT_HEADER_ENABLED=1 (test/dev environments).
    In production, tenant context comes from authenticated identity (JWT claims).
    """

    async def dispatch(self, request: Request, call_next):
        # Only allow header overrides in explicitly enabled environments
        if os.getenv("TENANT_HEADER_ENABLED", "0") == "1":
            team_id = request.headers.get("X-Team-Id")
            manager_id = request.headers.get("X-Manager-Id")

            if team_id:
                CURRENT_TEAM_ID.set(team_id)
                logger.debug("Set team_id=%s for request %s", team_id, request.url.path)
            if manager_id:
                CURRENT_MANAGER_ID.set(manager_id)

        response = await call_next(request)
        return response
