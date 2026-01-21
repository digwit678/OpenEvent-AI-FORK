"""
Integration configuration with toggle switch.

Toggle between JSON-based storage (current) and Supabase (integration).

Usage:
    # Check current mode
    from workflows.io.integration import is_integration_mode

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
    OE_HIL_ALL_LLM_REPLIES: Set to "true" to require HIL approval for all AI replies
    OE_EMAIL_PLAIN_TEXT: Set to "true" to strip Markdown from outgoing emails
    OE_ALLOW_JSON_FALLBACK: "true"/"false" to control JSON fallback on Supabase errors
                            Defaults to: allowed in dev, disabled in prod (ENV=prod)

Fallback Behavior (Testing Branch):
    When OE_INTEGRATION_MODE=supabase AND allow_json_fallback=True:
    - If a Supabase operation fails, LOUDLY log and fall back to JSON storage
    - This ensures development can continue even if Supabase is unavailable
    - Fallback events are clearly marked in logs with [SUPABASE_FALLBACK]

Production Behavior:
    When ENV=prod (or OE_ALLOW_JSON_FALLBACK=false):
    - Supabase errors propagate without fallback
    - This ensures data consistency in production
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


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
    use_supabase_snapshots: bool = False  # Use Supabase for info page snapshots

    # HIL for all LLM replies (default OFF for backwards compatibility)
    # When True: ALL AI-generated outbound replies go to "AI Reply Approval" HIL queue
    # When False: Current behavior (only specific actions require HIL)
    # TODO: Set to True when integrating with OpenEvent frontend for full manager control
    hil_all_llm_replies: bool = False

    # JSON fallback when Supabase fails (testing/dev only)
    # When True: If Supabase operation fails, LOUDLY fall back to JSON storage
    # When False: Supabase errors propagate (strict mode for production)
    # Automatically disabled when ENV=prod
    allow_json_fallback: bool = False

    # Email plain text mode (default OFF for rich Markdown formatting)
    # When True: Strip Markdown from email body for plain text compatibility
    # When False: Keep Markdown formatting (most email clients handle it)
    email_plain_text: bool = False

    @classmethod
    def from_env(cls) -> "IntegrationConfig":
        """Load configuration from environment variables."""
        mode = os.getenv("OE_INTEGRATION_MODE", "json").lower()
        hil_all_replies = os.getenv("OE_HIL_ALL_LLM_REPLIES", "false").lower() in ("true", "1", "yes")
        email_plain = os.getenv("OE_EMAIL_PLAIN_TEXT", "false").lower() in ("true", "1", "yes")
        env = os.getenv("ENV", "dev").lower()

        # JSON fallback: allowed in dev/testing, disabled in production
        # Can be explicitly controlled via OE_ALLOW_JSON_FALLBACK
        fallback_env = os.getenv("OE_ALLOW_JSON_FALLBACK", "").lower()
        if fallback_env:
            allow_fallback = fallback_env in ("true", "1", "yes")
        else:
            # Default: allow in dev/testing, disallow in prod
            allow_fallback = env != "prod"

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
            use_supabase_snapshots=mode == "supabase",
            # HIL toggle for all LLM replies
            hil_all_llm_replies=hil_all_replies,
            # JSON fallback (disabled in production)
            allow_json_fallback=allow_fallback and mode == "supabase",
            # Email plain text mode
            email_plain_text=email_plain,
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


def allow_json_fallback() -> bool:
    """Check if JSON fallback is allowed when Supabase fails.

    Returns True if:
    - Running in Supabase mode AND
    - Fallback is enabled (default in dev, disabled in prod)

    When True, Supabase errors will LOUDLY log and fall back to JSON storage.
    When False (production), Supabase errors propagate without fallback.
    """
    return INTEGRATION_CONFIG.allow_json_fallback


def get_team_id() -> Optional[str]:
    """Get the team_id for multi-tenant operations.

    Resolution order:
    1. Request-scoped contextvar (if set via X-Team-Id header)
    2. Environment variable OE_TEAM_ID (static fallback)
    """
    # Try request context first (set by TenantContextMiddleware)
    try:
        from api.middleware.tenant_context import get_request_team_id

        request_team_id = get_request_team_id()
        if request_team_id is not None:
            return request_team_id
    except ImportError:
        pass  # Middleware not available (e.g., in standalone scripts)

    # Fall back to static environment config
    return INTEGRATION_CONFIG.team_id


def get_system_user_id() -> Optional[str]:
    """Get the system_user_id for automated writes.

    Resolution order:
    1. Request-scoped contextvar (if set via X-Manager-Id header)
    2. Environment variable OE_SYSTEM_USER_ID (static fallback)
    """
    # Try request context first (set by TenantContextMiddleware)
    try:
        from api.middleware.tenant_context import get_request_manager_id

        request_manager_id = get_request_manager_id()
        if request_manager_id is not None:
            return request_manager_id
    except ImportError:
        pass  # Middleware not available (e.g., in standalone scripts)

    # Fall back to static environment config
    return INTEGRATION_CONFIG.system_user_id


def reload_config() -> None:
    """Reload configuration from environment (useful for testing)."""
    global INTEGRATION_CONFIG
    INTEGRATION_CONFIG = IntegrationConfig.from_env()


def _get_hil_setting_from_db() -> Optional[bool]:
    """Check database for HIL mode setting (allows runtime toggle).

    Returns None if not set in database, otherwise the boolean value.
    """
    try:
        # Import here to avoid circular dependency
        from workflow_email import load_db as wf_load_db
        db = wf_load_db()
        hil_config = db.get("config", {}).get("hil_mode", {})
        if "enabled" in hil_config:
            return hil_config["enabled"]
    except Exception as exc:
        # Database not available or error - fall back to env var
        logger.warning("[Config] Could not read HIL setting from DB: %s", exc)
    return None


# Cache for HIL setting to avoid repeated DB reads
_hil_setting_cache: Optional[bool] = None


def refresh_hil_setting() -> None:
    """Refresh HIL setting from database. Call after POST /api/config/hil-mode."""
    global _hil_setting_cache
    _hil_setting_cache = _get_hil_setting_from_db()


def is_hil_all_replies_enabled() -> bool:
    """Check if HIL approval is required for all AI replies.

    Priority order:
    0. ENV=dev → always False (no HIL in development)
    1. Database setting (if set) - allows runtime toggle via API
    2. Environment variable OE_HIL_ALL_LLM_REPLIES - server default
    3. False - backwards compatible default

    When True: ALL AI-generated outbound replies go to "AI Reply Approval" queue
    When False: Current behavior (only specific actions require HIL approval)
    """
    global _hil_setting_cache

    # DEV MODE: Disable HIL approval entirely for faster testing
    # Only enable HIL on production (main branch deployment)
    if os.getenv("ENV", "prod") == "dev":
        return False

    # Check cache first (set by refresh_hil_setting after API calls)
    if _hil_setting_cache is not None:
        return _hil_setting_cache

    # Check database (first call or cache invalidated)
    db_setting = _get_hil_setting_from_db()
    if db_setting is not None:
        _hil_setting_cache = db_setting
        return db_setting

    # Fall back to environment variable / config
    return INTEGRATION_CONFIG.hil_all_llm_replies


def is_email_plain_text_enabled() -> bool:
    """Check if email plain text mode is enabled.

    When True: Strip Markdown formatting from email body for plain text compatibility.
    When False: Keep Markdown formatting (most email clients handle it gracefully).

    Controlled by OE_EMAIL_PLAIN_TEXT environment variable.
    """
    return INTEGRATION_CONFIG.email_plain_text


def strip_markdown_for_email(text: str) -> str:
    """Convert Markdown-formatted text to plain text for email compatibility.

    Handles:
    - **bold** and __bold__ -> bold
    - *italic* and _italic_ -> italic
    - [links](url) -> links (url)
    - # Headers -> Headers
    - - bullet items -> • bullet items

    Preserves line breaks and spacing.
    """
    import re

    if not text:
        return text

    result = text

    # Remove bold markers: **text** or __text__
    result = re.sub(r'\*\*([^*]+)\*\*', r'\1', result)
    result = re.sub(r'__([^_]+)__', r'\1', result)

    # Remove italic markers: *text* or _text_ (be careful with underscores in words)
    result = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'\1', result)
    result = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', result)

    # Convert markdown links [text](url) -> text (url)
    result = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', result)

    # Remove header markers (keep text)
    result = re.sub(r'^#{1,6}\s*', '', result, flags=re.MULTILINE)

    # Convert dash bullets to Unicode bullets
    result = re.sub(r'^-\s+', '• ', result, flags=re.MULTILINE)

    # Convert backtick code to plain text
    result = re.sub(r'`([^`]+)`', r'\1', result)

    return result