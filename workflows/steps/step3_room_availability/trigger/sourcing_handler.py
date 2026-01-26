"""
Step 3 Product Sourcing Handler Functions.

Extracted from step3_handler.py as part of R8 refactoring (Jan 2026).

This module contains:
- handle_product_sourcing_request: Create HIL task for missing product sourcing
- advance_to_offer_from_sourcing: Advance to Step 4 after sourcing resolved

Usage:
    from .sourcing_handler import (
        handle_product_sourcing_request,
        advance_to_offer_from_sourcing,
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import update_event_metadata
from workflows.io.tasks import enqueue_task
from domain import TaskType
from debug.hooks import trace_marker

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Product Sourcing Request
# -----------------------------------------------------------------------------


def handle_product_sourcing_request(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    room_pending: Dict[str, Any],
    arrangement_result: Any,  # ArrangementDetectionResult
    thread_id: str,
) -> GroupResult:
    """Handle client request to arrange missing products.

    Creates a HIL task for the manager to source the product and pauses
    the workflow until the manager responds.

    Args:
        state: Current workflow state
        event_entry: Event database entry
        room_pending: The room_pending_decision with selected room info
        arrangement_result: Detection result with products to source
        thread_id: Thread ID for tracing

    Returns:
        GroupResult halting the workflow while waiting for manager
    """
    # Use client's explicitly chosen room if detected, otherwise use recommended room
    # This fixes the bug where client says "Room A please" but we lock Room B (recommended)
    if arrangement_result.chosen_room:
        selected_room = arrangement_result.chosen_room
        logger.debug("[Step3] Using client's EXPLICIT room choice: %s", selected_room)
    else:
        selected_room = room_pending.get("selected_room")
        logger.debug("[Step3] Using recommended room (no explicit choice): %s", selected_room)

    selected_status = room_pending.get("selected_status", "Available")
    products_to_source = arrangement_result.products_to_source

    # Lock the room - client confirmed by requesting arrangement
    if not event_entry.get("locked_room_id"):
        update_event_metadata(
            event_entry,
            locked_room_id=selected_room,
            room_eval_hash=room_pending.get("requirements_hash"),
            selected_room=selected_room,
            selected_room_status=selected_status,
        )
        event_entry.setdefault("flags", {})["room_selected"] = True
        trace_marker(
            thread_id,
            "room_locked_for_sourcing",
            detail=f"Locked {selected_room} while sourcing: {products_to_source}",
            owner_step="Step3_Room",
        )

    # Create HIL task for manager to source the product
    task_payload = {
        "step_id": 3,
        "event_id": event_entry.get("event_id"),
        "products": products_to_source,
        "room": selected_room,
        "thread_id": thread_id,
        "client_message": state.message.body if state.message else "",
        "action_type": "source_missing_product",
    }
    task_id = enqueue_task(
        state.db,
        TaskType.SOURCE_MISSING_PRODUCT,
        state.client_id or "",
        event_entry.get("event_id"),
        task_payload,
    )

    # Store pending sourcing state
    event_entry["sourcing_pending"] = {
        "task_id": task_id,
        "products": products_to_source,
        "room": selected_room,
        "requested_at": datetime.now().isoformat(),
    }

    # Clear room_pending_decision since we've moved past that stage
    if "room_pending_decision" in event_entry:
        del event_entry["room_pending_decision"]

    # Update state
    update_event_metadata(
        event_entry,
        current_step=3,
        thread_state="Waiting on HIL",
    )
    state.set_thread_state("Waiting on HIL")
    state.extras["persist"] = True

    # Prepare acknowledgment for client
    product_list = ", ".join(products_to_source) if products_to_source else "the requested items"
    draft = {
        "body": f"I'll check with our team about {product_list} for {selected_room}. I'll get back to you shortly.",
        "step": 3,
        "topic": "sourcing_request",
        "requires_approval": False,  # Send immediately
    }
    state.add_draft_message(draft)

    return GroupResult(
        action="sourcing_request_created",
        payload={
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "task_id": task_id,
            "products": products_to_source,
            "room": selected_room,
            "step": 3,
            "draft_messages": state.draft_messages,
        },
        halt=True,
    )


# -----------------------------------------------------------------------------
# Advance to Offer from Sourcing
# -----------------------------------------------------------------------------


def advance_to_offer_from_sourcing(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    thread_id: str,
) -> GroupResult:
    """Advance to Step 4 (offer) after sourcing is resolved.

    Called when:
    - Manager found the product and client auto-advances
    - Client chooses to continue without the product

    Args:
        state: Current workflow state
        event_entry: Event database entry
        thread_id: Thread ID for tracing

    Returns:
        GroupResult continuing to Step 4
    """
    trace_marker(
        thread_id,
        "advance_to_offer_from_sourcing",
        detail="Advancing to Step 4 after sourcing resolution",
        owner_step="Step3_Room",
    )

    # Update state for Step 4
    update_event_metadata(
        event_entry,
        current_step=4,
        thread_state="Processing",
    )
    state.current_step = 4
    state.set_thread_state("Processing")
    state.extras["persist"] = True

    return GroupResult(
        action="advance_to_offer",
        payload={
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "reason": "sourcing_resolved",
            "step": 4,
        },
        halt=False,  # Continue processing to Step 4
    )


# -----------------------------------------------------------------------------
# Backward-compatible aliases (prefixed with underscore)
# -----------------------------------------------------------------------------

_handle_product_sourcing_request = handle_product_sourcing_request
_advance_to_offer_from_sourcing = advance_to_offer_from_sourcing


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Public names
    "handle_product_sourcing_request",
    "advance_to_offer_from_sourcing",
    # Backward-compatible underscore aliases
    "_handle_product_sourcing_request",
    "_advance_to_offer_from_sourcing",
]
