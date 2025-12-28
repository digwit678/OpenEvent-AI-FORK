"""Gate functions for smart shortcuts eligibility.

This module handles the decision logic for whether smart shortcuts
should be allowed to run. Pure functions (no side effects except debug prints).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def shortcuts_allowed(event_entry: Dict[str, Any]) -> bool:
    """Gate smart shortcuts on confirmed date + capacity readiness.

    Returns True if the event is eligible for smart shortcut processing.
    """
    current_step = event_entry.get("current_step") or 0
    if current_step and isinstance(current_step, str):
        try:
            current_step = int(current_step)
        except ValueError:
            current_step = 0
    if current_step < 3:
        return False

    # [BILLING FLOW BYPASS] Don't intercept messages during billing capture flow
    # When offer is accepted and we're awaiting billing, let step 5 handle the message
    if event_entry.get("offer_accepted"):
        billing_req = event_entry.get("billing_requirements") or {}
        if billing_req.get("awaiting_billing_for_accept"):
            return False

    if event_entry.get("date_confirmed") is not True:
        return False

    if coerce_participants(event_entry) is not None:
        return True

    shortcuts = event_entry.get("shortcuts") or {}
    return bool(shortcuts.get("capacity_ok"))


def coerce_participants(event_entry: Dict[str, Any]) -> Optional[int]:
    """Extract and normalize participant count from event entry.

    Returns the participant count as an integer, or None if not available.
    """
    requirements = event_entry.get("requirements") or {}
    raw = requirements.get("number_of_participants")
    if raw in (None, "", "Not specified", "none"):
        raw = requirements.get("participants")
    if raw in (None, "", "Not specified", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None


def debug_shortcut_gate(
    state: str,
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any]
) -> None:
    """Log debug information about shortcut gate decisions.

    Only outputs when WF_DEBUG_STATE=1 is set.
    """
    if os.getenv("WF_DEBUG_STATE") != "1":
        return
    info = {
        "state": state,
        "step": event_entry.get("current_step"),
        "date_confirmed": event_entry.get("date_confirmed"),
        "participants": (event_entry.get("requirements") or {}).get("number_of_participants"),
        "capacity_shortcut": (event_entry.get("shortcuts") or {}).get("capacity_ok"),
        "wish_products": (event_entry.get("wish_products") or []),
        "user_shortcut": (user_info or {}).get("shortcut_capacity_ok"),
    }
    formatted = " ".join(f"{key}={value}" for key, value in info.items())
    print(f"[WF DEBUG][shortcuts] {formatted}")


# Compatibility aliases for internal use (underscore prefix convention)
_shortcuts_allowed = shortcuts_allowed
_coerce_participants = coerce_participants
_debug_shortcut_gate = debug_shortcut_gate
