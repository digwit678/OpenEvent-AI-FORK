"""
LLM Provider Configuration Helper.

Provides a centralized way to get the current LLM provider settings.
This is used by detection (intent/entity) and verbalization to determine
which LLM backend to use.

Hybrid Mode (default):
- Intent/Entity extraction: Gemini (cheaper, good for structured extraction)
- Verbalization: OpenAI (better quality for client-facing text)

Priority order:
1. Database setting (runtime toggle via admin UI)
2. Environment variables (INTENT_PROVIDER, ENTITY_PROVIDER, VERBALIZER_PROVIDER)
3. AGENT_MODE environment variable (sets all to same provider)
4. Defaults: gemini for extraction, openai for verbalization
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

Provider = Literal["openai", "gemini", "stub"]

# Fallback chain: if primary fails, try these in order
# NOTE: No stub fallback in production - we want real LLM responses
PROVIDER_FALLBACK_CHAIN = {
    "gemini": ["openai"],  # Gemini fails → try OpenAI
    "openai": ["gemini"],  # OpenAI fails → try Gemini
    "stub": [],            # Stub has no fallback (only used in testing)
}


@dataclass
class LLMProviderSettings:
    """Current LLM provider settings."""
    intent_provider: Provider
    entity_provider: Provider
    verbalization_provider: Provider
    source: str  # "database", "environment", or "default"


def get_fallback_providers(primary: Provider) -> list:
    """Get fallback providers if primary fails."""
    return PROVIDER_FALLBACK_CHAIN.get(primary, ["stub"])


# Cache to avoid repeated database reads
_cached_settings: Optional[LLMProviderSettings] = None


def get_llm_providers(*, force_reload: bool = False) -> LLMProviderSettings:
    """
    Get the current LLM provider configuration.

    Checks in order:
    1. Database config (allows runtime toggle)
    2. Environment variables
    3. Defaults (hybrid mode)

    Args:
        force_reload: If True, bypass cache and reload from database

    Returns:
        LLMProviderSettings with current provider for each operation type
    """
    global _cached_settings

    if _cached_settings is not None and not force_reload:
        return _cached_settings

    # Try database first
    try:
        from backend.workflows.io.database import load_db
        db = load_db()
        llm_config = db.get("config", {}).get("llm_provider", {})

        if llm_config.get("intent_provider") or llm_config.get("entity_provider"):
            _cached_settings = LLMProviderSettings(
                intent_provider=llm_config.get("intent_provider", "gemini"),
                entity_provider=llm_config.get("entity_provider", "gemini"),
                verbalization_provider=llm_config.get("verbalization_provider", "openai"),
                source="database",
            )
            return _cached_settings
    except Exception:
        pass  # Database not available, use env/defaults

    # Fall back to environment variables
    agent_mode = os.getenv("AGENT_MODE", "").lower()

    # If AGENT_MODE is set, use it as default for extraction
    if agent_mode in ("openai", "gemini", "stub"):
        default_extraction = agent_mode
    else:
        default_extraction = "gemini"  # Default: Gemini for extraction

    _cached_settings = LLMProviderSettings(
        intent_provider=os.getenv("INTENT_PROVIDER", default_extraction),
        entity_provider=os.getenv("ENTITY_PROVIDER", default_extraction),
        verbalization_provider=os.getenv("VERBALIZER_PROVIDER", "openai"),
        source="environment",
    )
    return _cached_settings


def clear_provider_cache() -> None:
    """Clear the cached provider settings. Call after config changes."""
    global _cached_settings
    _cached_settings = None


def get_intent_provider() -> Provider:
    """Get the provider for intent classification."""
    return get_llm_providers().intent_provider


def get_entity_provider() -> Provider:
    """Get the provider for entity extraction."""
    return get_llm_providers().entity_provider


def get_verbalization_provider() -> Provider:
    """Get the provider for verbalization/draft composition."""
    return get_llm_providers().verbalization_provider


# ============================================================================
# HYBRID MODE ENFORCEMENT
# ============================================================================
# By default, the system MUST run in hybrid mode (using both Gemini and OpenAI).
# This ensures:
# - Cost efficiency (Gemini for intent/entity extraction)
# - Quality (OpenAI for client-facing verbalization)
# - Testing coverage (both LLM providers are exercised)
#
# OpenAI-only mode is ONLY allowed as a fallback if Gemini is unavailable.
# To bypass this enforcement (NOT recommended), set:
#   OE_BYPASS_HYBRID_ENFORCEMENT=1  (environment variable)
#   OR config.hybrid_enforcement.enabled=false (database setting)
# ============================================================================

import logging as _logging
_hybrid_logger = _logging.getLogger(__name__)


def is_hybrid_mode(settings: Optional[LLMProviderSettings] = None) -> bool:
    """
    Check if the current configuration is in hybrid mode.

    Hybrid mode means using BOTH Gemini and OpenAI for different operations.
    This is the recommended configuration for production.

    Returns True if:
    - At least one of intent/entity/verbalization uses Gemini
    - AND at least one uses OpenAI
    - (i.e., not all same provider)

    Returns False if all operations use the same provider (single-provider mode).
    """
    if settings is None:
        settings = get_llm_providers()

    providers_used = {
        settings.intent_provider,
        settings.entity_provider,
        settings.verbalization_provider,
    }

    # Stub doesn't count - it's for testing only
    providers_used.discard("stub")

    # Hybrid = using more than one real provider
    return len(providers_used) > 1


def is_hybrid_enforcement_enabled() -> bool:
    """
    Check if hybrid mode enforcement is enabled.

    Returns True by default. Set to False to allow single-provider modes.

    To bypass enforcement:
    - Set env var: OE_BYPASS_HYBRID_ENFORCEMENT=1
    - OR set database config: config.hybrid_enforcement.enabled=false
    """
    # Check environment variable first (highest priority for emergency bypass)
    env_bypass = os.getenv("OE_BYPASS_HYBRID_ENFORCEMENT", "").lower()
    if env_bypass in ("1", "true", "yes"):
        return False

    # Check database config
    try:
        from backend.workflows.io.database import load_db
        db = load_db()
        enforcement_config = db.get("config", {}).get("hybrid_enforcement", {})
        if "enabled" in enforcement_config:
            return enforcement_config.get("enabled", True)
    except Exception:
        pass  # Database not available, use default

    # Default: enforcement ON
    return True


def validate_hybrid_mode(*, raise_on_failure: bool = False, is_production: bool = False) -> tuple:
    """
    Validate that the system is running in hybrid mode.

    This function should be called at startup to ensure proper configuration.

    Args:
        raise_on_failure: If True, raises RuntimeError on validation failure
        is_production: If True, treat this as production (stricter enforcement)

    Returns:
        Tuple of (is_valid: bool, message: str, settings: LLMProviderSettings)

    Raises:
        RuntimeError: If raise_on_failure=True and validation fails
    """
    settings = get_llm_providers(force_reload=True)
    enforcement_enabled = is_hybrid_enforcement_enabled()
    hybrid = is_hybrid_mode(settings)

    if hybrid:
        msg = (
            f"✅ Hybrid mode active: "
            f"I:{settings.intent_provider[:3]}, "
            f"E:{settings.entity_provider[:3]}, "
            f"V:{settings.verbalization_provider[:3]} "
            f"(source: {settings.source})"
        )
        return (True, msg, settings)

    # Not in hybrid mode
    single_provider = settings.intent_provider  # All same in single-provider mode

    if not enforcement_enabled:
        msg = (
            f"⚠️  Single-provider mode ({single_provider}): "
            f"Hybrid enforcement BYPASSED. "
            f"This is only for emergency fallback. "
            f"(source: {settings.source})"
        )
        _hybrid_logger.warning(msg)
        return (True, msg, settings)  # Allowed but warned

    # Enforcement enabled, but not in hybrid mode - this is a problem
    msg = (
        f"❌ HYBRID MODE REQUIRED: System configured for {single_provider}-only mode. "
        f"OpenEvent requires hybrid mode (Gemini + OpenAI) for production. "
        f"To bypass (emergency only): set OE_BYPASS_HYBRID_ENFORCEMENT=1"
    )

    if is_production:
        _hybrid_logger.critical(msg)
        # In production, this is a critical error
        # TODO: Send email notification to developers
        if raise_on_failure:
            raise RuntimeError(msg)
    else:
        _hybrid_logger.error(msg)
        if raise_on_failure:
            raise RuntimeError(msg)

    return (False, msg, settings)
