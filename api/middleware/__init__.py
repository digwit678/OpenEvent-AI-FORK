"""Middleware package for API layer."""

from .tenant_context import (
    TenantContextMiddleware,
    get_request_team_id,
    get_request_manager_id,
)

from .auth import (
    AuthMiddleware,
    get_current_user_id,
    get_current_user_role,
    require_admin_role,
    # P2 stub functions (enable when Supabase storage is implemented)
    verify_team_membership,
    clear_membership_cache,
)

from .rate_limit import (
    setup_rate_limiting,
    get_rate_limit_status,
)

__all__ = [
    "TenantContextMiddleware",
    "get_request_team_id",
    "get_request_manager_id",
    "AuthMiddleware",
    "get_current_user_id",
    "get_current_user_role",
    "require_admin_role",
    # P2 stub functions
    "verify_team_membership",
    "clear_membership_cache",
    "setup_rate_limiting",
    "get_rate_limit_status",
]
