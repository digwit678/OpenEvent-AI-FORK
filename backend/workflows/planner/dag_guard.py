"""
Smart Shortcuts - DAG Guard.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module enforces the dependency graph (DAG) for workflow operations:
- Room selection requires confirmed date
- Product add requires locked room
- Billing requires sent offer

When a DAG violation is detected, a prerequisite prompt is emitted.

Usage:
    from .dag_guard import dag_guard, is_date_confirmed, is_room_locked
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner
    from .shortcuts_types import ParsedIntent


def is_date_confirmed(planner: "_ShortcutPlanner") -> bool:
    """Check if the event has a confirmed date.

    Returns True if:
    - date_confirmed flag is True, OR
    - requested_window has a date_iso or display_date
    """
    if planner.event.get("date_confirmed") is True:
        return True
    requested = planner.event.get("requested_window") or {}
    if requested.get("date_iso") or requested.get("display_date"):
        return True
    return False


def is_room_locked(planner: "_ShortcutPlanner") -> bool:
    """Check if the event has a locked room."""
    return bool(planner.event.get("locked_room_id"))


def can_collect_billing(planner: "_ShortcutPlanner") -> bool:
    """Check if billing can be collected for this event.

    Returns True if:
    - Current step >= 6, OR
    - Offer status is sent/accepted/finalized/approved/ready
    """
    current_step = planner.event.get("current_step") or 1
    if current_step >= 6:
        return True
    status = str(planner.event.get("offer_status") or "").lower()
    return status in {"sent", "accepted", "finalized", "finalised", "approved", "ready"}


def set_dag_block(planner: "_ShortcutPlanner", reason: Optional[str]) -> None:
    """Set the DAG block reason, maintaining priority order.

    Priority order (lower wins):
    1. room_requires_date
    2. products_require_room
    3. billing_after_offer
    """
    if not reason:
        return
    order = {"room_requires_date": 0, "products_require_room": 1, "billing_after_offer": 2}
    current_rank = order.get(planner._dag_block_reason, 99)
    next_rank = order.get(reason, 99)
    if next_rank < current_rank:
        planner._dag_block_reason = reason
    if reason == planner._dag_block_reason:
        planner.telemetry.dag_blocked = planner._dag_block_reason
        planner.state.telemetry.dag_blocked = planner._dag_block_reason


def ensure_prerequisite_prompt(
    planner: "_ShortcutPlanner",
    reason: Optional[str],
    intent: Optional["ParsedIntent"] = None,
) -> None:
    """Emit a prerequisite prompt for the given DAG block reason.

    - room_requires_date: Emit date choice intent
    - products_require_room: Emit availability request
    - billing_after_offer: Emit offer_prepare request
    """
    if not reason:
        return
    if reason == "room_requires_date":
        planner._ensure_date_choice_intent()
        return
    if reason == "products_require_room":
        if any(item.type == "availability" for item in planner.needs_input):
            return
        payload: Dict[str, Any] = {"reason": "room_requires_date"}
        pending = planner.event.get("room_pending_decision") or {}
        room = pending.get("selected_room")
        if room:
            payload["room"] = room
        planner._add_needs_input("availability", payload, reason="room_requires_date")
        return
    if reason == "billing_after_offer":
        if any(item.type == "offer_prepare" for item in planner.needs_input):
            return
        planner._add_needs_input("offer_prepare", {}, reason="billing_after_offer")


def dag_guard(planner: "_ShortcutPlanner", intent: "ParsedIntent") -> Tuple[bool, Optional[str]]:
    """Check if the intent is allowed by the DAG.

    Returns:
        Tuple of (allowed: bool, reason: Optional[str])
        - If allowed is False, reason explains why (e.g., "room_requires_date")
    """
    reason: Optional[str] = None
    if intent.type == "room_selection" and not is_date_confirmed(planner):
        reason = "room_requires_date"
    elif intent.type == "product_add" and not is_room_locked(planner):
        reason = "products_require_room"
    elif intent.type == "billing" and not can_collect_billing(planner):
        reason = "billing_after_offer"
    allowed = reason is None
    return allowed, reason


__all__ = [
    "dag_guard",
    "is_date_confirmed",
    "is_room_locked",
    "can_collect_billing",
    "set_dag_block",
    "ensure_prerequisite_prompt",
]
