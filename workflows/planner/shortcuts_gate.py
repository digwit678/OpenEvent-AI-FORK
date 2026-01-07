"""Gate functions for smart shortcuts eligibility.

This module handles the decision logic for whether smart shortcuts
should be allowed to run.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def shortcuts_allowed(event_entry: Dict[str, Any]) -> bool:
    """Gate smart shortcuts on confirmed date + capacity readiness.

    Returns True if the event is eligible for smart shortcut processing.
    """
    import sys
    print(f"[SHORTCUTS_GATE] ENTRY - current_step={event_entry.get('current_step')}, date_confirmed={event_entry.get('date_confirmed')}", flush=True)
    sys.stderr.write(f"[SHORTCUTS_GATE] ENTRY - current_step={event_entry.get('current_step')}, date_confirmed={event_entry.get('date_confirmed')}\n")
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

    # [PRODUCT ARRANGEMENT BYPASS] Don't intercept room selection when client might
    # be requesting to arrange missing products. Let step3_handler detect the intent.
    room_pending = event_entry.get("room_pending_decision")
    locked_room = event_entry.get("locked_room_id")
    import sys
    print(f"[SHORTCUTS_GATE] room_pending={bool(room_pending)}, locked_room={locked_room}, missing_products={(room_pending or {}).get('missing_products', [])}", flush=True)
    sys.stderr.write(f"[SHORTCUTS_GATE] room_pending={bool(room_pending)}, locked_room={locked_room}, missing_products={(room_pending or {}).get('missing_products', [])}\n")
    if room_pending and not locked_room:
        missing_products = room_pending.get("missing_products", [])
        if missing_products:
            # Room not locked yet and there are missing products - defer to step3
            print(f"[SHORTCUTS_GATE] BLOCKING shortcuts - missing products: {missing_products}", flush=True)
            sys.stderr.write(f"[SHORTCUTS_GATE] BLOCKING shortcuts - missing products: {missing_products}\n")
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
    logger.debug("[WF DEBUG][shortcuts] %s", formatted)


# Compatibility aliases for internal use (underscore prefix convention)
_shortcuts_allowed = shortcuts_allowed
_coerce_participants = coerce_participants
_debug_shortcut_gate = debug_shortcut_gate
