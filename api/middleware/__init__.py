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
    "setup_rate_limiting",
    "get_rate_limit_status",
]
