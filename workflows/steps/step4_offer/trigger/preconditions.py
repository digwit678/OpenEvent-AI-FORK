"""
Step 4 Offer Precondition Evaluation and Routing.

Extracted from step4_handler.py as part of god-file refactoring (Jan 2026).

This module contains:
- evaluate_preconditions: Check P1-P4 gates before offer generation
- has_capacity: Verify participant count is available
- route_to_owner_step: Route back to step 2 or 3 when preconditions fail
- handle_products_pending: Handle missing products state

Usage:
    from .preconditions import (
        evaluate_preconditions,
        has_capacity,
        route_to_owner_step,
        handle_products_pending,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple, Union

from debug.hooks import trace_detour, trace_gate
from debug.trace import set_hil_open
from workflow.state import WorkflowStep, write_stage
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import append_audit_entry, update_event_metadata

from .product_ops import products_ready as _products_ready

logger = logging.getLogger(__name__)


def evaluate_preconditions(
    event_entry: Dict[str, Any],
    current_requirements_hash: Optional[str],
    thread_id: str,
) -> Optional[Tuple[str, Union[int, str]]]:
    """Evaluate P1-P4 preconditions for offer generation.

    Returns:
        None if all preconditions pass.
        Tuple of (reason_code, target) if a precondition fails:
            - ("P1", 2): date not confirmed, route to step 2
            - ("P2", 3): room not locked or hash mismatch, route to step 3
            - ("P3", 3): no capacity info, route to step 3
            - ("P4", "products"): products not ready, handle products flow
    """
    # P1: Date must be confirmed
    date_ok = bool(event_entry.get("date_confirmed"))
    trace_gate(thread_id, "Step4_Offer", "P1 date_confirmed", date_ok, {})
    if not date_ok:
        return "P1", 2

    # P2: Room must be locked with matching requirements hash
    locked_room_id = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")
    logger.debug(
        "[Step4] P2 CHECK: locked_room_id=%s, room_eval_hash=%s, current_req_hash=%s",
        locked_room_id,
        room_eval_hash,
        current_requirements_hash,
    )
    p2_ok = (
        locked_room_id
        and current_requirements_hash
        and room_eval_hash
        and current_requirements_hash == room_eval_hash
    )
    logger.debug(
        "[Step4] P2 RESULT: p2_ok=%s, match=%s",
        p2_ok,
        current_requirements_hash == room_eval_hash if room_eval_hash else "N/A",
    )
    trace_gate(
        thread_id,
        "Step4_Offer",
        "P2 room_locked",
        bool(p2_ok),
        {
            "locked_room_id": locked_room_id,
            "room_eval_hash": room_eval_hash,
            "requirements_hash": current_requirements_hash,
        },
    )
    if not p2_ok:
        return "P2", 3

    # P3: Must have capacity (participant count)
    capacity_ok = has_capacity(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P3 capacity_confirmed", capacity_ok, {})
    if not capacity_ok:
        return "P3", 3

    # P4: Products must be ready
    products_ok = _products_ready(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P4 products_ready", products_ok, {})
    if not products_ok:
        return "P4", "products"

    return None


def has_capacity(event_entry: Dict[str, Any]) -> bool:
    """Check if participant count is available from any source.

    Searches in order:
    1. requirements.number_of_participants
    2. event_data["Number of Participants"]
    3. captured.participants

    Returns True if a positive participant count is found.
    """
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")

    if participants is None:
        participants = (event_entry.get("event_data") or {}).get("Number of Participants")

    if participants is None:
        participants = (event_entry.get("captured") or {}).get("participants")

    try:
        return int(str(participants).strip()) > 0
    except (TypeError, ValueError, AttributeError):
        return False


def route_to_owner_step(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    target_step: int,
    reason_code: str,
    thread_id: str,
) -> GroupResult:
    """Route to an earlier step (2 or 3) when preconditions fail.

    Updates workflow state and creates appropriate audit trail.
    """
    caller_step = WorkflowStep.STEP_4
    target_enum = WorkflowStep(f"step_{target_step}")
    write_stage(event_entry, current_step=target_enum, caller_step=caller_step)

    # Clear stale negotiation state when detouring back - old offer no longer valid
    if target_step in (2, 3):
        event_entry.pop("negotiation_pending_decision", None)

    thread_state = "Awaiting Client" if target_step in (2, 3) else "Waiting on HIL"
    update_event_metadata(event_entry, thread_state=thread_state)
    append_audit_entry(event_entry, 4, target_step, f"offer_gate_{reason_code.lower()}")

    trace_detour(
        thread_id,
        "Step4_Offer",
        _step_name(target_step),
        f"offer_gate_{reason_code.lower()}",
        {},
    )

    state.current_step = target_step
    state.caller_step = caller_step.numeric
    state.set_thread_state(thread_state)
    set_hil_open(thread_id, thread_state == "Waiting on HIL")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "target_step": target_step,
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_detour", payload=payload, halt=False)


def handle_products_pending(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    reason_code: str,
) -> GroupResult:
    """Handle the products pending state when P4 fails.

    Shows product prompt or waits for client response.
    """
    products_state = event_entry.setdefault("products_state", {})
    first_prompt = not products_state.get("awaiting_client_products")

    # If Step 3 already showed catering teaser in room availability message,
    # don't send a separate products prompt - wait for user to respond to that
    if products_state.get("catering_teaser_shown") and first_prompt:
        logger.debug("[Step4] Skipping products prompt - catering teaser already shown in Step 3")
        products_state["awaiting_client_products"] = True
        append_audit_entry(event_entry, 4, 4, "offer_products_deferred_to_step3_teaser")

        # No message - just wait for client response to Step 3's catering question
        write_stage(event_entry, current_step=WorkflowStep.STEP_4)
        update_event_metadata(event_entry, thread_state="Awaiting Client")

        state.current_step = 4
        state.caller_step = event_entry.get("caller_step")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "missing": [reason_code],
            "thread_state": state.thread_state,
            "draft_messages": state.draft_messages,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="offer_products_pending_silent", payload=payload, halt=True)

    if first_prompt:
        products_state["awaiting_client_products"] = True
        prompt = (
            "Before I prepare your tailored proposal, could you share which catering or add-ons you'd like to include? "
            "Let me know if you'd prefer to proceed without extras."
        )
        draft_message = {
            "body_markdown": prompt,
            "step": 4,
            "next_step": "Share preferred products",
            "thread_state": "Awaiting Client",
            "topic": "offer_products_prompt",
            "requires_approval": False,
            "actions": [
                {
                    "type": "share_products",
                    "label": "Provide preferred products",
                }
            ],
        }
        state.add_draft_message(draft_message)
        append_audit_entry(event_entry, 4, 4, "offer_products_prompt")
    else:
        # Still awaiting products - re-prompt with variation to avoid silent fallback
        repeat_prompt = (
            "I still need your product preferences before preparing the offer. "
            "Would you like catering, beverages, or any add-ons? "
            "You can also say 'no extras' to proceed without additional products."
        )
        draft_message = {
            "body_markdown": repeat_prompt,
            "step": 4,
            "next_step": "Share preferred products",
            "thread_state": "Awaiting Client",
            "topic": "offer_products_repeat_prompt",
            "requires_approval": False,
            "actions": [
                {
                    "type": "share_products",
                    "label": "Add products",
                },
                {
                    "type": "skip_products",
                    "label": "No extras needed",
                },
            ],
        }
        state.add_draft_message(draft_message)
        append_audit_entry(event_entry, 4, 4, "offer_products_repeat_prompt")

    write_stage(event_entry, current_step=WorkflowStep.STEP_4)
    update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = 4
    state.caller_step = event_entry.get("caller_step")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_products_pending", payload=payload, halt=True)


def _step_name(step: int) -> str:
    """Map step number to trace-friendly name."""
    mapping = {
        1: "Step1_Intake",
        2: "Step2_Date",
        3: "Step3_Room",
        4: "Step4_Offer",
        5: "Step5_Negotiation",
        6: "Step6_Transition",
        7: "Step7_Confirmation",
    }
    return mapping.get(step, f"Step{step}")


# Backwards compatibility aliases (prefixed with underscore)
_evaluate_preconditions = evaluate_preconditions
_has_capacity = has_capacity
_route_to_owner_step = route_to_owner_step
_handle_products_pending = handle_products_pending
_step_name_alias = _step_name


__all__ = [
    "evaluate_preconditions",
    "has_capacity",
    "route_to_owner_step",
    "handle_products_pending",
    # Private aliases for backwards compatibility
    "_evaluate_preconditions",
    "_has_capacity",
    "_route_to_owner_step",
    "_handle_products_pending",
]
