"""
Authentication middleware with toggle for production.

Supports two modes:
  - AUTH_MODE=api_key: Simple API key validation (initial prod rollout)
  - AUTH_MODE=supabase_jwt: Supabase JWT validation with claims (future)

Default: AUTH_ENABLED=0 (no auth checks - dev/test behavior unchanged)

Environment Variables:
  - AUTH_ENABLED: "0" (default) or "1" to enable
  - AUTH_MODE: "api_key" (default) or "supabase_jwt"
  - API_KEY: Required when AUTH_MODE=api_key
  - SUPABASE_JWT_SECRET: Required when AUTH_MODE=supabase_jwt
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Request-scoped auth context (for Supabase JWT mode)
CURRENT_USER_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_USER_ID", default=None)
CURRENT_USER_ROLE: ContextVar[Optional[str]] = ContextVar("CURRENT_USER_ROLE", default=None)

# Public routes that don't require authentication
ALLOWLIST_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/workflow/health",
)

# Routes that are public even with auth enabled
# Note: /api/qna was removed - venue data should require auth in production.
# Venues wanting public Q&A should proxy through their own authenticated layer.
ALLOWLIST_EXACT = {
    "/",
}


def get_current_user_id() -> Optional[str]:
    """Get user_id from authenticated request, or None if not authenticated."""
    return CURRENT_USER_ID.get()


def get_current_user_role() -> Optional[str]:
    """Get user role from authenticated request, or None if not authenticated."""
    return CURRENT_USER_ROLE.get()


def _extract_bearer_token(auth_header: str) -> Optional[str]:
    """Extract token from 'Bearer <token>' header."""
    if not auth_header:
        return None
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


def _validate_api_key(token: Optional[str]) -> Tuple[bool, str]:
    """
    Validate API key against environment variable.

    Returns:
        (is_valid, error_message)
    """
    expected_key = os.getenv("API_KEY", "").strip()

    if not expected_key:
        logger.warning("AUTH_ENABLED=1 but API_KEY not configured")
        return False, "server_misconfigured"

    if not token:
        return False, "missing_token"

    if token != expected_key:
        # Log with redacted token for debugging
        redacted = token[:4] + "..." if len(token) > 4 else "***"
        logger.warning("Invalid API key attempt: %s", redacted)
        return False, "invalid_token"

    return True, ""


def _validate_supabase_jwt(token: Optional[str]) -> Tuple[bool, str, dict]:
    """
    Validate Supabase JWT and extract claims.

    Returns:
        (is_valid, error_message, claims_dict)

    Note: This is a placeholder for Phase 3. Currently returns error.
    When implemented, will:
      1. Validate JWT signature using SUPABASE_JWT_SECRET or JWKS
      2. Extract claims (sub, team_id, role)
      3. Set contextvars for downstream access
    """
    if not token:
        return False, "missing_token", {}

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()

    if not jwt_secret:
        logger.warning("AUTH_MODE=supabase_jwt but SUPABASE_JWT_SECRET not configured")
        return False, "server_misconfigured", {}

    # TODO Phase 3: Implement JWT validation
    # For now, return not implemented
    # When ready:
    #   import jwt
    #   try:
    #       payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    #       return True, "", {
    #           "user_id": payload.get("sub"),
    #           "team_id": payload.get("team_id"),
    #           "role": payload.get("role", "user"),
    #       }
    #   except jwt.ExpiredSignatureError:
    #       return False, "token_expired", {}
    #   except jwt.InvalidTokenError:
    #       return False, "invalid_token", {}

    return False, "supabase_jwt_not_implemented", {}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware with production toggle.

    When AUTH_ENABLED=0 (default):
        - No authentication checks
        - All requests pass through unchanged
        - Current dev/test behavior preserved

    When AUTH_ENABLED=1:
        - Enforces authentication on non-allowlisted routes
        - Supports API key and Supabase JWT modes
        - Returns 401 for unauthorized requests
    """

    async def dispatch(self, request: Request, call_next):
        # Check if auth is enabled
        if os.getenv("AUTH_ENABLED", "0") != "1":
            # Auth disabled - pass through without checks
            return await call_next(request)

        path = request.url.path

        # Check allowlist prefixes
        if path.startswith(ALLOWLIST_PREFIXES):
            return await call_next(request)

        # Check exact allowlist matches
        if path in ALLOWLIST_EXACT:
            return await call_next(request)

        # Get auth mode and token
        auth_mode = os.getenv("AUTH_MODE", "api_key")
        auth_header = request.headers.get("Authorization", "")
        token = _extract_bearer_token(auth_header)

        # Also check X-Api-Key header as fallback for internal tools
        if not token:
            token = request.headers.get("X-Api-Key", "").strip()

        # Validate based on mode
        if auth_mode == "api_key":
            is_valid, error = _validate_api_key(token)
            if not is_valid:
                return JSONResponse(
                    {"error": "unauthorized", "detail": error},
                    status_code=401,
                )
            return await call_next(request)

        elif auth_mode == "supabase_jwt":
            is_valid, error, claims = _validate_supabase_jwt(token)
            if not is_valid:
                return JSONResponse(
                    {"error": "unauthorized", "detail": error},
                    status_code=401,
                )

            # Set auth context for downstream use
            if claims.get("user_id"):
                CURRENT_USER_ID.set(claims["user_id"])
            if claims.get("role"):
                CURRENT_USER_ROLE.set(claims["role"])

            # In Supabase JWT mode, also set tenant context from claims
            # This integrates with multi-tenancy (overrides X-Team-Id header)
            if claims.get("team_id"):
                from backend.api.middleware.tenant_context import CURRENT_TEAM_ID
                CURRENT_TEAM_ID.set(claims["team_id"])

            return await call_next(request)

        else:
            logger.error("Invalid AUTH_MODE: %s", auth_mode)
            return JSONResponse(
                {"error": "server_error", "detail": "invalid_auth_mode"},
                status_code=500,
            )
