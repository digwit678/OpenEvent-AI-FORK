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

    Active when:
    1. TENANT_HEADER_ENABLED=1 (explicit opt-in for test/dev)
    2. AUTH_MODE=supabase_jwt (implicit multi-tenancy in JWT mode)

    In JWT mode, the AuthMiddleware sets team_id from JWT claims first,
    but X-Team-Id header can still override for testing/admin scenarios.
    """

    async def dispatch(self, request: Request, call_next):
        # Enable tenant headers when:
        # 1. Explicitly enabled (TENANT_HEADER_ENABLED=1)
        # 2. Running in Supabase JWT auth mode (implicit multi-tenancy)
        auth_mode = os.getenv("AUTH_MODE", "api_key")
        header_enabled = os.getenv("TENANT_HEADER_ENABLED", "0") == "1"

        if header_enabled or auth_mode == "supabase_jwt":
            team_id = request.headers.get("X-Team-Id")
            manager_id = request.headers.get("X-Manager-Id")

            if team_id:
                CURRENT_TEAM_ID.set(team_id)
                logger.debug("Set team_id=%s for request %s", team_id, request.url.path)
            if manager_id:
                CURRENT_MANAGER_ID.set(manager_id)

        response = await call_next(request)
        return response
