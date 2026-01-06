"""
Smart Shortcuts - Intent Executor.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles intent execution for the shortcuts planner:
- Intent dispatch (routing to appropriate apply method)
- Room selection application
- Participants update application
- Question selection and generation

Usage:
    from .intent_executor import (
        execute_intent, apply_room_selection, apply_participants_update,
        select_next_question, question_for_intent,
    )
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from workflows.common.requirements import requirements_hash
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.io.database import append_audit_entry, update_event_metadata

from .shortcuts_flags import _budget_default_currency, _capture_budget_on_hil
from .shortcuts_types import ParsedIntent

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner


# --------------------------------------------------------------------------
# Intent dispatch
# --------------------------------------------------------------------------


def execute_intent(planner: "_ShortcutPlanner", intent: ParsedIntent) -> bool:
    """Execute a parsed intent by routing to the appropriate apply method.

    Args:
        planner: The shortcuts planner instance
        intent: The intent to execute

    Returns:
        True if intent was successfully executed, False otherwise
    """
    if intent.type == "date_confirmation":
        return planner._apply_date_confirmation(intent.data["window"])
    if intent.type == "room_selection":
        return apply_room_selection(planner, intent.data["room"])
    if intent.type == "participants_update":
        return apply_participants_update(planner, intent.data["participants"])
    if intent.type == "product_add":
        return planner._apply_product_add(intent.data.get("items") or [])
    return False


# --------------------------------------------------------------------------
# Room selection
# --------------------------------------------------------------------------


def apply_room_selection(planner: "_ShortcutPlanner", requested_room: str) -> bool:
    """Apply a room selection intent.

    Locks the room if it matches the pending decision, updates event metadata,
    and transitions to Step 4.

    Args:
        planner: The shortcuts planner instance
        requested_room: The room name to lock

    Returns:
        True if room was successfully locked, False otherwise
    """
    pending = planner.event.get("room_pending_decision") or {}
    selected = pending.get("selected_room") or planner.event.get("locked_room_id")

    if not selected or selected.lower() != str(requested_room).strip().lower():
        return False

    status = pending.get("selected_status") or "Available"
    requirements_hash_value = (
        pending.get("requirements_hash") or planner.event.get("requirements_hash")
    )

    update_event_metadata(
        planner.event,
        locked_room_id=selected,
        room_eval_hash=requirements_hash_value,
        current_step=4,
        thread_state="In Progress",
        status="Option",  # Room selected -> calendar blocked as Option
    )
    planner.event.pop("room_pending_decision", None)
    append_audit_entry(planner.event, 3, 4, "room_locked_via_shortcut")

    planner.state.current_step = 4
    planner.state.extras["persist"] = True
    planner.telemetry.executed_intents.append("room_selection")
    planner.summary_lines.append(f"* Room locked: {selected} ({status}) -> Status: Option")
    planner.room_checked = True

    return True


# --------------------------------------------------------------------------
# Participants update
# --------------------------------------------------------------------------


def apply_participants_update(planner: "_ShortcutPlanner", participants: int) -> bool:
    """Apply a participants/headcount update intent.

    Updates the requirements with new participant count and recomputes hash.

    Args:
        planner: The shortcuts planner instance
        participants: The new participant count

    Returns:
        True (always succeeds)
    """
    requirements = dict(planner.event.get("requirements") or {})
    requirements["number_of_participants"] = participants
    req_hash = requirements_hash(requirements)

    update_event_metadata(
        planner.event,
        requirements=requirements,
        requirements_hash=req_hash,
    )

    planner.state.extras["persist"] = True
    planner.telemetry.executed_intents.append("participants_update")
    planner.summary_lines.append(f"* Headcount updated: {participants} guests")

    return True


# --------------------------------------------------------------------------
# Question selection and generation
# --------------------------------------------------------------------------


def select_next_question(
    planner: "_ShortcutPlanner",
) -> Optional[Dict[str, Any]]:
    """Select the next question to ask based on priority order.

    Scans needs_input list and returns the highest priority intent
    that needs user input.

    Args:
        planner: The shortcuts planner instance

    Returns:
        Dict with "intent" and "data" keys, or None if no questions needed
    """
    if not planner.needs_input:
        return None

    priority_map = {intent.type: intent for intent in planner.needs_input}

    for candidate in planner.priority_order:
        intent = priority_map.get(candidate)
        if intent:
            return {"intent": intent.type, "data": intent.data}

    # Fall back to first deferred
    intent = planner.needs_input[0]
    return {"intent": intent.type, "data": intent.data}


def question_for_intent(
    planner: "_ShortcutPlanner",
    intent_type: str,
    data: Dict[str, Any],
) -> str:
    """Generate a question string for a given intent type.

    Creates a natural language question to prompt user for the
    information needed by the intent.

    Args:
        planner: The shortcuts planner instance
        intent_type: Type of intent needing input
        data: Intent data for context

    Returns:
        Question string to display to user
    """
    if intent_type == "time":
        chosen_date = planner.user_info.get("event_date") or format_iso_date_to_ddmmyyyy(
            planner.user_info.get("date")
        )
        if chosen_date:
            return f"What start and end time should we reserve for {chosen_date}? (e.g., 14:00-18:00)"
        return "What start and end time should we reserve? (e.g., 14:00-18:00)"

    if intent_type == "availability":
        room = data.get("room")
        if room:
            return f"Should I run availability for {room}? Let me know if you'd prefer a different space."
        return "Which room would you like me to check availability for?"

    if intent_type == "site_visit":
        return "Would you like me to propose a few slots for a site visit?"

    if intent_type == "date_choice":
        return "Which date should I check for you? Feel free to share a couple of options."

    if intent_type == "budget":
        currency = _budget_default_currency()
        return f'Could you share a budget cap? For example "{currency} 60 total" or "{currency} 30 per item".'

    if intent_type == "offer_hil":
        items = data.get("items") or []
        item_names = ", ".join(
            missing_item_display(planner, item) for item in items
        )
        budget = data.get("budget") or planner.budget_info
        currency = (budget or {}).get("currency") or _budget_default_currency()

        if budget:
            budget_text = budget.get("text") or format_money(
                planner, budget.get("amount"), currency
            )
            return (
                f"Would you like me to send a request to our manager for {item_names} with budget {budget_text}? "
                "You'll receive an email once the manager replies."
            )

        if _capture_budget_on_hil():
            return (
                f"Would you like me to send a request to our manager for {item_names}? "
                f'If so, let me know a budget cap (e.g., "{currency} 60 total" or "{currency} 30 per item"). '
                "You'll receive an email once the manager replies."
            )

        return (
            f"Would you like me to send a request to our manager for {item_names}? "
            "You'll receive an email once they reply."
        )

    if intent_type == "billing":
        return "Could you confirm the billing address when you're ready?"

    if intent_type == "offer_prepare":
        return "Should I start drafting the offer next, or is there another detail you'd like me to capture?"

    if intent_type == "product_followup":
        items = data.get("items") or []
        names = ", ".join(item.get("name") or "the item" for item in items) or "the pending item"
        return (
            f"I queued {names} for the next update because we already confirmed two items. "
            "Should I keep that plan, or is there another detail you'd like me to prioritize now?"
        )

    return "Let me know the next detail you'd like me to update."


# --------------------------------------------------------------------------
# Helper functions (used by question_for_intent)
# --------------------------------------------------------------------------


def missing_item_display(planner: "_ShortcutPlanner", item: Dict[str, Any]) -> str:
    """Format a missing item for display.

    Args:
        planner: The shortcuts planner instance
        item: Item dict with name/quantity

    Returns:
        Formatted string like "2x Champagne" or "Champagne"
    """
    # Delegate to product_handler's implementation
    from .product_handler import missing_item_display as _missing_item_display_impl

    return _missing_item_display_impl(item)


def format_money(
    planner: "_ShortcutPlanner",
    amount: Optional[float],
    currency: str,
) -> str:
    """Format a monetary amount.

    Args:
        planner: The shortcuts planner instance
        amount: Amount to format
        currency: Currency code

    Returns:
        Formatted string like "CHF 500.00"
    """
    # Delegate to product_handler's implementation
    from .product_handler import format_money as _format_money_impl

    return _format_money_impl(amount, currency)


__all__ = [
    # Intent dispatch
    "execute_intent",
    # Room selection
    "apply_room_selection",
    # Participants update
    "apply_participants_update",
    # Question handling
    "select_next_question",
    "question_for_intent",
    # Helpers
    "missing_item_display",
    "format_money",
]
