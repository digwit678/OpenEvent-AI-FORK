"""Change application module.

Applies change routing decisions from DAG-based change propagation
and handles room lock management during detours.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from workflows.change_propagation import ChangeType
from workflows.io.database import append_audit_entry, update_event_metadata

logger = logging.getLogger(__name__)


@dataclass
class ChangeApplicationResult:
    """Result of applying change routing."""
    detoured_to_step2: bool = False
    change_detour: bool = False
    billing_cleared: bool = False


def apply_dag_routing(
    event_entry: Dict[str, Any],
    decision: Any,  # RoutingDecision from change_propagation
    change_type: ChangeType,
    previous_step: int,
    in_billing_flow: bool,
    thread_id: str,
    trace_marker_fn: Optional[Any] = None,
) -> ChangeApplicationResult:
    """Apply DAG routing decision to event entry.

    Handles:
    - Setting caller_step for return path
    - Updating current_step
    - Managing room lock based on change type
    - Clearing billing flow state on date detours

    Args:
        event_entry: Event record to update
        decision: RoutingDecision from route_change_on_updated_variable
        change_type: Type of change detected
        previous_step: Step before routing
        in_billing_flow: Whether currently in billing flow
        thread_id: For tracing
        trace_marker_fn: Optional trace_marker function for logging

    Returns:
        ChangeApplicationResult with flags for downstream logic
    """
    result = ChangeApplicationResult()

    # Apply caller_step if not already set
    if decision.updated_caller_step is not None and event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=decision.updated_caller_step)
        if trace_marker_fn:
            trace_marker_fn(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": previous_step,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                },
                owner_step="Step1_Intake",
            )

    # Apply step change if different from current
    if decision.next_step != previous_step:
        update_event_metadata(event_entry, current_step=decision.next_step)
        audit_reason = f"{change_type.value}_change_detected"
        append_audit_entry(event_entry, previous_step, decision.next_step, audit_reason)

        # Clear billing flow state on date detour
        if in_billing_flow and change_type.value == "date":
            billing_req = event_entry.get("billing_requirements") or {}
            billing_req["awaiting_billing_for_accept"] = False
            event_entry["billing_requirements"] = billing_req
            event_entry["offer_accepted"] = False
            logger.info("[Step1][DETOUR_FIX] Cleared billing flow state for date change detour")
            result.billing_cleared = True

        # Handle room lock based on change type and target step
        if change_type.value in ("date", "requirements"):
            _apply_room_lock_updates(event_entry, decision.next_step, change_type.value)
            if decision.next_step == 2:
                result.detoured_to_step2 = True
            elif decision.next_step == 3:
                result.change_detour = True

    return result


def _apply_room_lock_updates(
    event_entry: Dict[str, Any],
    next_step: int,
    change_type_value: str,
) -> None:
    """Apply room lock updates based on change type and target step.

    Args:
        event_entry: Event record to update
        next_step: Target step
        change_type_value: "date" or "requirements"
    """
    if next_step not in (2, 3):
        return

    sourced = event_entry.get("sourced_products")
    sourced_for_current_room = (
        sourced and sourced.get("room") == event_entry.get("locked_room_id")
    )

    if next_step == 2:
        if change_type_value == "date":
            # DATE change to Step 2: KEEP locked_room_id so Step 3 can fast-skip
            # if the room is still available on the new date
            # CRITICAL: Also invalidate offer_hash - a new offer with the new date
            # must be generated even if the room is still available
            update_event_metadata(
                event_entry,
                date_confirmed=False,
                room_eval_hash=None,  # Invalidate for re-verification
                offer_hash=None,  # Invalidate offer - must regenerate with new date
                # NOTE: Do NOT clear locked_room_id for date changes
            )
        else:
            # REQUIREMENTS change to Step 2: clear room lock since room may no longer fit
            # EXCEPTION: Don't clear room lock if sourcing was completed for this room
            if sourced_for_current_room:
                update_event_metadata(
                    event_entry,
                    date_confirmed=False,
                    room_eval_hash=None,
                )
            else:
                update_event_metadata(
                    event_entry,
                    date_confirmed=False,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
    elif next_step == 3:
        # Going to Step 3 for requirements change: clear room lock but KEEP date confirmed
        # EXCEPTION: Don't clear room lock if sourcing was completed for this room
        if sourced_for_current_room:
            # Sourcing completed - protect room lock, just invalidate hash
            update_event_metadata(
                event_entry,
                room_eval_hash=None,
            )
        else:
            update_event_metadata(
                event_entry,
                room_eval_hash=None,
                locked_room_id=None,
            )


__all__ = [
    "ChangeApplicationResult",
    "apply_dag_routing",
]
