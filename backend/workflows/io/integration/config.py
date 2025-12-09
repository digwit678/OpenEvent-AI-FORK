"""
Integration configuration with toggle switch.

Toggle between JSON-based storage (current) and Supabase (integration).

Usage:
    # Check current mode
    from backend.workflows.io.integration import is_integration_mode

    if is_integration_mode():
        # Use Supabase adapter
    else:
        # Use JSON file adapter (current behavior)

Environment Variables:
    OE_INTEGRATION_MODE: Set to "supabase" to enable integration mode
    OE_SUPABASE_URL: Supabase project URL (required in integration mode)
    OE_SUPABASE_KEY: Supabase anon/service key (required in integration mode)
    OE_TEAM_ID: Team UUID for multi-tenant operations
    OE_SYSTEM_USER_ID: System user UUID for automated writes
    OE_EMAIL_ACCOUNT_ID: Email account UUID for email operations
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntegrationConfig:
    """Configuration for Supabase integration."""

    # Toggle: "json" (current) or "supabase" (integration)
    mode: str = "json"

    # Supabase connection (only used when mode="supabase")
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

    # Multi-tenant identifiers (required for Supabase mode)
    team_id: Optional[str] = None
    system_user_id: Optional[str] = None
    email_account_id: Optional[str] = None

    # Feature flags for gradual rollout
    use_supabase_clients: bool = False  # Use Supabase for client lookup
    use_supabase_events: bool = False   # Use Supabase for event storage
    use_supabase_tasks: bool = False    # Use Supabase for HIL tasks
    use_supabase_emails: bool = False   # Use Supabase for email storage

    @classmethod
    def from_env(cls) -> "IntegrationConfig":
        """Load configuration from environment variables."""
        mode = os.getenv("OE_INTEGRATION_MODE", "json").lower()

        return cls(
            mode=mode,
            supabase_url=os.getenv("OE_SUPABASE_URL"),
            supabase_key=os.getenv("OE_SUPABASE_KEY"),
            team_id=os.getenv("OE_TEAM_ID"),
            system_user_id=os.getenv("OE_SYSTEM_USER_ID"),
            email_account_id=os.getenv("OE_EMAIL_ACCOUNT_ID"),
            # Feature flags default to True in supabase mode
            use_supabase_clients=mode == "supabase",
            use_supabase_events=mode == "supabase",
            use_supabase_tasks=mode == "supabase",
            use_supabase_emails=mode == "supabase",
        )

    def is_supabase_mode(self) -> bool:
        """Check if running in Supabase integration mode."""
        return self.mode == "supabase"

    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []

        if self.mode == "supabase":
            if not self.supabase_url:
                errors.append("OE_SUPABASE_URL is required in supabase mode")
            if not self.supabase_key:
                errors.append("OE_SUPABASE_KEY is required in supabase mode")
            if not self.team_id:
                errors.append("OE_TEAM_ID is required in supabase mode")
            if not self.system_user_id:
                errors.append("OE_SYSTEM_USER_ID is required in supabase mode")

        return errors


# Global config instance - loaded once at module import
INTEGRATION_CONFIG = IntegrationConfig.from_env()


def is_integration_mode() -> bool:
    """Quick check if running in Supabase integration mode."""
    return INTEGRATION_CONFIG.is_supabase_mode()


def get_team_id() -> Optional[str]:
    """Get the configured team_id for multi-tenant operations."""
    return INTEGRATION_CONFIG.team_id


def get_system_user_id() -> Optional[str]:
    """Get the configured system_user_id for automated writes."""
    return INTEGRATION_CONFIG.system_user_id


def reload_config() -> None:
    """Reload configuration from environment (useful for testing)."""
    global INTEGRATION_CONFIG
    INTEGRATION_CONFIG = IntegrationConfig.from_env()