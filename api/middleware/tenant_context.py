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
import logging
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

logger = logging.getLogger(__name__)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract tenant context from request headers.

    Active when:
    1. TENANT_HEADER_ENABLED=1 (explicit opt-in for test/dev)
    2. AUTH_MODE=supabase_jwt (team derived from JWT claims)

    In JWT mode, team_id comes from auth claims by default.
    X-Team-Id override is only allowed when TENANT_HEADER_ENABLED=1.
    """

    async def dispatch(self, request: Request, call_next):
        # Always scope tenant context to the current request.
        team_token = CURRENT_TEAM_ID.set(None)
        manager_token = CURRENT_MANAGER_ID.set(None)

        try:
            auth_mode = os.getenv("AUTH_MODE", "api_key")
            header_enabled = os.getenv("TENANT_HEADER_ENABLED", "0") == "1"

            team_id: Optional[str] = None
            manager_id: Optional[str] = None

            # In JWT mode, auth middleware attaches the team claim on request state.
            if auth_mode == "supabase_jwt":
                team_id = getattr(request.state, "auth_team_id", None)

            # Header-based overrides are opt-in only.
            if header_enabled:
                header_team_id = request.headers.get("X-Team-Id")
                header_manager_id = request.headers.get("X-Manager-Id")
                if header_team_id:
                    team_id = header_team_id
                if header_manager_id:
                    manager_id = header_manager_id

            if team_id:
                CURRENT_TEAM_ID.set(team_id)
                logger.debug("Set team_id=%s for request %s", team_id, request.url.path)
            if manager_id:
                CURRENT_MANAGER_ID.set(manager_id)

            return await call_next(request)
        finally:
            CURRENT_TEAM_ID.reset(team_token)
            CURRENT_MANAGER_ID.reset(manager_token)
