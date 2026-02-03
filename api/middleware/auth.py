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

# Import HTTPException for require_admin_role
try:
    from fastapi import HTTPException
except ImportError:
    # Fallback for non-FastAPI environments
    HTTPException = None  # type: ignore

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

# Routes that are public even with auth enabled (read-only info endpoints)
ALLOWLIST_EXACT = {
    "/",
    "/api/qna",
}


def get_current_user_id() -> Optional[str]:
    """Get user_id from authenticated request, or None if not authenticated."""
    return CURRENT_USER_ID.get()


def get_current_user_role() -> Optional[str]:
    """Get user role from authenticated request, or None if not authenticated."""
    return CURRENT_USER_ROLE.get()


def require_admin_role() -> None:
    """
    Verify the authenticated user has admin or owner role.
    Call this at the start of admin-only route handlers.

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if role is insufficient

    Usage in route handlers:
        @router.post("/config/setting")
        async def update_setting(data: SettingModel):
            require_admin_role()  # Guard at the start
            # ... rest of handler
    """
    if HTTPException is None:
        raise RuntimeError("FastAPI not available - cannot use require_admin_role")

    user_id = get_current_user_id()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    role = get_current_user_role()
    if role not in ("admin", "owner"):
        logger.warning(
            "Admin access denied for user=%s role=%s",
            user_id[:8] + "..." if user_id else "unknown",
            role,
        )
        raise HTTPException(status_code=403, detail="Admin role required")


# =============================================================================
# P2 STUB: Supabase Database Verification (NOT YET ACTIVE)
# =============================================================================
# TODO: Enable this when P2 (Supabase Storage) is implemented.
# This provides real-time verification of team membership against the database,
# catching cases where a user is removed from a team but still has a valid JWT.
#
# To enable:
# 1. Implement P2 (Supabase Storage) first
# 2. Set SUPABASE_VERIFY_MEMBERSHIP=1 in .env
# 3. Call verify_team_membership() in the middleware after JWT validation
# =============================================================================

# Cache for team membership verification (5 min TTL)
_membership_cache: dict = {}
_MEMBERSHIP_CACHE_TTL = 300  # 5 minutes


async def verify_team_membership(user_id: str, team_id: str) -> str:
    """
    [P2 STUB] Verify user is still a member of team and return current role.

    This function queries Supabase to verify:
    1. User is an active member of the team (team_members_new table)
    2. OR user is the team owner (teams table)

    Returns:
        str: The user's role ("admin", "owner", "member", etc.)

    Raises:
        HTTPException 403 if user is not a team member

    NOTE: This is a STUB - requires P2 (Supabase Storage) to be implemented first.
    """
    import time

    if HTTPException is None:
        raise RuntimeError("FastAPI not available")

    # Check cache first
    cache_key = f"{user_id}:{team_id}"
    cached = _membership_cache.get(cache_key)
    if cached:
        cached_role, cached_time = cached
        if time.time() - cached_time < _MEMBERSHIP_CACHE_TTL:
            logger.debug("Team membership cache hit for user=%s team=%s", user_id[:8], team_id[:8])
            return cached_role

    # P2 STUB: When Supabase is integrated, uncomment this code:
    # -----------------------------------------------------------------
    # from supabase import create_client
    #
    # supabase_url = os.getenv("OE_SUPABASE_URL")
    # supabase_key = os.getenv("OE_SUPABASE_KEY")
    #
    # if not supabase_url or not supabase_key:
    #     logger.warning("Supabase not configured, skipping membership verification")
    #     return "user"  # Fallback to JWT claim
    #
    # client = create_client(supabase_url, supabase_key)
    #
    # # Check team_members_new table
    # result = client.table("team_members_new")\
    #     .select("role")\
    #     .eq("team_id", team_id)\
    #     .eq("user_id", user_id)\
    #     .eq("invitation_status", "active")\
    #     .execute()
    #
    # if result.data:
    #     role = result.data[0]["role"]
    #     _membership_cache[cache_key] = (role, time.time())
    #     return role
    #
    # # Check if user is team owner
    # team_result = client.table("teams")\
    #     .select("owner_id")\
    #     .eq("id", team_id)\
    #     .execute()
    #
    # if team_result.data and team_result.data[0]["owner_id"] == user_id:
    #     _membership_cache[cache_key] = ("owner", time.time())
    #     return "owner"
    #
    # # Not a member
    # logger.warning("User %s not a member of team %s", user_id[:8], team_id[:8])
    # raise HTTPException(status_code=403, detail="Not a team member")
    # -----------------------------------------------------------------

    # STUB: For now, just return the JWT role (trust claims)
    logger.debug("P2 stub: verify_team_membership not active, trusting JWT claims")
    return get_current_user_role() or "user"


def clear_membership_cache(user_id: Optional[str] = None, team_id: Optional[str] = None) -> int:
    """
    Clear the membership verification cache.

    Call this when:
    - A user is added/removed from a team
    - A user's role changes
    - You need to force re-verification

    Args:
        user_id: Clear cache for specific user (None = all users)
        team_id: Clear cache for specific team (None = all teams)

    Returns:
        int: Number of cache entries cleared
    """
    global _membership_cache

    if user_id is None and team_id is None:
        count = len(_membership_cache)
        _membership_cache = {}
        return count

    to_remove = []
    for key in _membership_cache:
        cached_user, cached_team = key.split(":")
        if (user_id is None or cached_user == user_id) and \
           (team_id is None or cached_team == team_id):
            to_remove.append(key)

    for key in to_remove:
        del _membership_cache[key]

    return len(to_remove)


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

    Supabase stores custom claims in `app_metadata`, so we check both
    app_metadata and top-level payload for team_id and role.

    Expected JWT payload structure:
        {
            "sub": "user-uuid",
            "app_metadata": {
                "team_id": "team-uuid",
                "role": "admin"
            },
            ...
        }
    """
    if not token:
        return False, "missing_token", {}

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()

    if not jwt_secret:
        logger.warning("AUTH_MODE=supabase_jwt but SUPABASE_JWT_SECRET not configured")
        return False, "server_misconfigured", {}

    try:
        import jwt as pyjwt

        # Supabase uses HS256 by default
        payload = pyjwt.decode(token, jwt_secret, algorithms=["HS256"])

        # Extract app_metadata (where Supabase stores custom claims)
        app_metadata = payload.get("app_metadata", {})

        # Check both app_metadata and top-level for team_id/role
        # (Supabase recommends app_metadata, but support both for flexibility)
        return True, "", {
            "user_id": payload.get("sub"),
            "team_id": app_metadata.get("team_id") or payload.get("team_id"),
            "role": app_metadata.get("role") or payload.get("role", "user"),
        }

    except ImportError:
        logger.error("PyJWT not installed - run: pip install PyJWT")
        return False, "server_misconfigured", {}

    except Exception as e:
        # Use module name to access exception types
        import jwt as pyjwt

        if isinstance(e, pyjwt.ExpiredSignatureError):
            return False, "token_expired", {}

        if isinstance(e, pyjwt.InvalidTokenError):
            logger.debug("JWT validation failed: %s", e)
            return False, "invalid_token", {}

        # Unexpected error
        logger.error("Unexpected JWT error: %s", e)
        return False, "invalid_token", {}


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
                from api.middleware.tenant_context import CURRENT_TEAM_ID
                CURRENT_TEAM_ID.set(claims["team_id"])

            return await call_next(request)

        else:
            logger.error("Invalid AUTH_MODE: %s", auth_mode)
            return JSONResponse(
                {"error": "server_error", "detail": "invalid_auth_mode"},
                status_code=500,
            )
