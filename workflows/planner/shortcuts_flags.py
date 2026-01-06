"""Environment flags for smart shortcuts configuration.

This module centralizes all SMART_SHORTCUTS_* and related flag parsing.
All functions are pure (no side effects beyond reading env vars).
"""
from __future__ import annotations

import os
from typing import List

from config.flags import env_flag


def shortcuts_enabled() -> bool:
    """Check if smart shortcuts feature is enabled."""
    return env_flag("SMART_SHORTCUTS", False)


def max_combined() -> int:
    """Maximum number of intents to combine in one turn."""
    value = os.environ.get(
        "SMART_SHORTCUTS_MAX_COMBINED",
        os.environ.get("MAX_COMBINED", "3")
    )
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


def legacy_shortcuts_allowed() -> bool:
    """Check if legacy shortcut mode is enabled."""
    return env_flag("LEGACY_SHORTCUTS_ALLOWED", False)


def needs_input_priority() -> List[str]:
    """Priority order for needs_input items."""
    default = ["time", "availability", "site_visit", "offer_hil", "budget", "billing"]
    raw = os.environ.get("SMART_SHORTCUTS_NEEDS_INPUT")
    if not raw:
        return default
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or default


def product_flow_enabled() -> bool:
    """Check if product flow feature is enabled."""
    return env_flag("PRODUCT_FLOW_ENABLED", False)


def capture_budget_on_hil() -> bool:
    """Check if budget should be captured during HIL."""
    return env_flag("CAPTURE_BUDGET_ON_HIL", False)


def no_unsolicited_menus() -> bool:
    """Check if unsolicited menus should be suppressed."""
    return env_flag("NO_UNSOLICITED_MENUS", False)


def event_scoped_upsell_enabled() -> bool:
    """Check if event-scoped upsell is enabled."""
    return env_flag("EVENT_SCOPED_UPSELL", False)


def budget_default_currency() -> str:
    """Default currency for budget parsing."""
    return os.environ.get("BUDGET_DEFAULT_CURRENCY", "CHF")


def budget_parse_strict() -> bool:
    """Check if strict budget parsing is enabled."""
    return env_flag("BUDGET_PARSE_STRICT", False)


def max_missing_items_per_hil() -> int:
    """Maximum number of missing items to show per HIL request."""
    try:
        return max(1, int(os.environ.get("MAX_MISSING_ITEMS_PER_HIL", "10") or 10))
    except (TypeError, ValueError):
        return 10


def atomic_turns_enabled() -> bool:
    """Check if atomic turns mode is enabled."""
    return env_flag("ATOMIC_TURNS", False)


def shortcut_allow_date_room() -> bool:
    """Check if date+room shortcut combo is allowed."""
    return env_flag("SHORTCUT_ALLOW_DATE_ROOM", True)


# Compatibility aliases for internal use (underscore prefix convention)
_flag_enabled = shortcuts_enabled
_max_combined = max_combined
_legacy_shortcuts_allowed = legacy_shortcuts_allowed
_needs_input_priority = needs_input_priority
_product_flow_enabled = product_flow_enabled
_capture_budget_on_hil = capture_budget_on_hil
_no_unsolicited_menus = no_unsolicited_menus
_event_scoped_upsell_enabled = event_scoped_upsell_enabled
_budget_default_currency = budget_default_currency
_budget_parse_strict = budget_parse_strict
_max_missing_items_per_hil = max_missing_items_per_hil
