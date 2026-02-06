"""
MODULE: workflows/manager_actions.py
PURPOSE: Process manager-initiated actions from the frontend and adapt workflow state.

CAPTURE-AND-ADVANCE PATTERN:
Manager actions follow a different flow than client messages:
1. Manager adds/updates a value (date, room, billing, etc.)
2. Value is captured as CONFIRMED (no client re-confirmation needed)
3. Gatekeeper is refreshed to check which gates are now satisfied
4. Workflow auto-advances if gates allow (e.g., room selection -> offer)
5. Next step generates a response that goes through HIL (always-review mode)
6. Client is notified of changes but doesn't need to re-confirm

ACTION TYPES:
- DATE_CHANGE/SET: Manager sets/changes date -> Captured as confirmed, advance if gates allow
- ROOM_CHANGE/SET: Manager sets/changes room -> Captured as locked, advance to offer if ready
- REQUIREMENTS_UPDATE: Manager updates participants/layout -> Update hashes, re-check gates
- BILLING_UPDATE: Manager adds billing info -> Check confirmation gate
- OFFER_UPDATE: Manager modifies offer -> Regenerate and resend
- SITE_VISIT_RESCHEDULE: Manager reschedules -> Update and notify client
- HIL_APPROVE/REJECT: Manager reviews message -> Send or discard
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from workflows.io.database import (
    append_audit_entry,
    update_event_metadata,
)
from workflows.common.requirements import requirements_hash
from workflows.common.gatekeeper import refresh_gatekeeper, explain_step7_gate
from activity.persistence import log_workflow_activity

logger = logging.getLogger(__name__)


class ManagerActionType(Enum):
    """Types of manager-initiated actions."""
    DATE_CHANGE = "date_change"
    ROOM_CHANGE = "room_change"
    ROOM_CANCELLATION = "room_cancellation"
    REQUIREMENTS_UPDATE = "requirements_update"
    BILLING_UPDATE = "billing_update"
    OFFER_UPDATE = "offer_update"
    SITE_VISIT_RESCHEDULE = "site_visit_reschedule"
    HIL_APPROVE = "hil_approve"
    HIL_REJECT = "hil_reject"


@dataclass
class ManagerActionResult:
    """Result of processing a manager action."""
    success: bool
    action_type: ManagerActionType
    event_id: str
    previous_step: int
    new_step: int
    workflow_advanced: bool  # True if workflow auto-advanced due to gate satisfaction
    needs_client_notification: bool
    notification_draft: Optional[str] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    gates_satisfied: List[str] = field(default_factory=list)
    draft_messages: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action_type": self.action_type.value,
            "event_id": self.event_id,
            "previous_step": self.previous_step,
            "new_step": self.new_step,
            "workflow_advanced": self.workflow_advanced,
            "needs_client_notification": self.needs_client_notification,
            "notification_draft": self.notification_draft,
            "error": self.error,
            "details": self.details,
            "gates_satisfied": self.gates_satisfied,
            "draft_messages": self.draft_messages,
        }


def _determine_next_step(event_entry: Dict[str, Any]) -> int:
    """
    Determine the next appropriate workflow step based on gate satisfaction.

    Gate requirements:
    - Step 2 (Date): date_confirmed is True
    - Step 3 (Room): locked_room_id set AND room_eval_hash matches requirements_hash
    - Step 4 (Offer): offer_hash exists with valid line items
    - Step 7 (Confirmation): date_confirmed + locked_room + offer_accepted + billing

    CRITICAL: We check room_eval_hash in addition to locked_room_id because:
    - Manager date/requirements changes invalidate room_eval_hash
    - If room_eval_hash is None/mismatched, room needs re-validation even if locked

    Returns the step the workflow should advance to.
    """
    gatekeeper = refresh_gatekeeper(event_entry)

    # Check gates in order to find the right step
    if not event_entry.get("date_confirmed"):
        return 2  # Need date confirmation

    # Step 3 gate: Need BOTH locked room AND valid room evaluation
    # BUG FIX: Check room_eval_hash matches requirements_hash, not just locked_room_id
    locked_room = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")
    requirements_hash = event_entry.get("requirements_hash")

    # Room needs re-evaluation if:
    # - No locked room, OR
    # - No room_eval_hash (room not evaluated), OR
    # - room_eval_hash doesn't match current requirements_hash (stale evaluation)
    room_needs_reeval = (
        not locked_room
        or not room_eval_hash
        or (requirements_hash and room_eval_hash != requirements_hash)
    )

    if room_needs_reeval:
        return 3  # Need room selection/re-evaluation

    if not gatekeeper.get("step4"):  # No valid offer
        return 4  # Need to generate offer

    # Check Step 7 readiness
    step7_explain = explain_step7_gate(event_entry)
    if step7_explain["ready"]:
        return 7  # Ready for confirmation

    # Offer exists but not accepted, or missing billing - stay at current negotiation
    current = event_entry.get("current_step", 4)
    if current >= 4:
        return current

    return 5  # Default to negotiation if offer exists


def process_manager_action(
    event_entry: Dict[str, Any],
    action_type: ManagerActionType,
    payload: Dict[str, Any],
    *,
    manager_id: Optional[str] = None,
) -> ManagerActionResult:
    """
    Process a manager-initiated action using capture-and-advance pattern.

    Unlike client messages, manager actions:
    1. Don't require LLM detection (action is explicit)
    2. Values are captured as CONFIRMED (no client re-confirmation)
    3. Workflow auto-advances when gates are satisfied
    4. Client is notified but doesn't need to re-confirm

    Args:
        event_entry: Event dict from workflow database
        action_type: Type of manager action
        payload: Action-specific data
        manager_id: Optional manager identifier for audit

    Returns:
        ManagerActionResult with processing details and any generated drafts
    """
    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    logger.info(
        "[MANAGER_ACTION] Processing %s for event %s (step %d)",
        action_type.value, event_id, current_step
    )

    try:
        # Dispatch to handler based on action type (Python 3.9 compatible)
        if action_type == ManagerActionType.DATE_CHANGE:
            return _handle_manager_date_change(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.ROOM_CHANGE:
            return _handle_manager_room_change(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.ROOM_CANCELLATION:
            return _handle_manager_room_cancellation(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.REQUIREMENTS_UPDATE:
            return _handle_manager_requirements_update(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.BILLING_UPDATE:
            return _handle_manager_billing_update(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.OFFER_UPDATE:
            return _handle_manager_offer_update(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.SITE_VISIT_RESCHEDULE:
            return _handle_manager_site_visit_reschedule(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.HIL_APPROVE:
            return _handle_manager_hil_approve(event_entry, payload, manager_id)
        elif action_type == ManagerActionType.HIL_REJECT:
            return _handle_manager_hil_reject(event_entry, payload, manager_id)
        else:
            return ManagerActionResult(
                success=False,
                action_type=action_type,
                event_id=event_id,
                previous_step=current_step,
                new_step=current_step,
                workflow_advanced=False,
                needs_client_notification=False,
                error=f"Unknown action type: {action_type}",
            )
    except Exception as e:
        logger.exception("[MANAGER_ACTION] Error processing %s: %s", action_type.value, e)
        return ManagerActionResult(
            success=False,
            action_type=action_type,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error=str(e),
        )


# =============================================================================
# DATE CHANGE HANDLER (Capture-and-Advance)
# =============================================================================


def _handle_manager_date_change(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated date change.

    CAPTURE-AND-ADVANCE PATTERN:
    1. Capture new date as chosen_date
    2. Mark date_confirmed=True (manager selection = confirmed)
    3. Refresh gatekeeper to check what's now satisfied
    4. Auto-advance workflow if room gate ready
    5. Notify client of date change (don't wait for re-confirmation)
    """
    from workflows.notifications.manager_action_drafts import generate_date_change_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    old_date = event_entry.get("chosen_date")
    new_date = payload.get("new_date")

    if not new_date:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.DATE_CHANGE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="new_date is required",
        )

    # CAPTURE: Set date as CONFIRMED (manager selection = confirmed)
    update_event_metadata(
        event_entry,
        chosen_date=new_date,
        date_confirmed=True,  # Manager selection = confirmed
        room_eval_hash=None,  # Invalidate - room availability may change on new date
        offer_hash=None,  # Invalidate - offer shows date
    )

    # ADVANCE: Check what step we should be at now
    new_step = _determine_next_step(event_entry)
    workflow_advanced = new_step > current_step

    # Update current_step if advancing
    if new_step != current_step:
        update_event_metadata(event_entry, current_step=new_step)

    # Refresh gatekeeper to see what's satisfied
    gatekeeper = refresh_gatekeeper(event_entry)
    gates_satisfied = [k for k, v in gatekeeper.items() if v]

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        new_step,
        f"manager_date_set:{old_date}->{new_date}:confirmed=True",
        manager_id or "manager",
    )

    # Log activity for manager visibility
    log_workflow_activity(
        event_entry,
        "date_confirmed",
        date=new_date,
    )

    # Generate client notification (informational, not requiring confirmation)
    notification_draft = generate_date_change_notification(
        event_entry, old_date, new_date
    )

    logger.info(
        "[MANAGER_ACTION] Date set to %s for event %s (confirmed=True, advancing to step %d)",
        new_date, event_id, new_step
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.DATE_CHANGE,
        event_id=event_id,
        previous_step=current_step,
        new_step=new_step,
        workflow_advanced=workflow_advanced,
        needs_client_notification=True,
        notification_draft=notification_draft,
        gates_satisfied=gates_satisfied,
        details={
            "old_date": old_date,
            "new_date": new_date,
            "date_confirmed": True,
        },
    )


# =============================================================================
# ROOM CHANGE HANDLER (Capture-and-Advance)
# =============================================================================


def _handle_manager_room_change(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated room selection/change.

    CAPTURE-AND-ADVANCE PATTERN:
    1. Capture room as locked_room_id (satisfies Step 3 gate)
    2. Refresh gatekeeper to see what's now satisfied
    3. If date confirmed + room locked -> advance to Step 4 (offer)
    4. Notify client of room selection
    """
    from workflows.notifications.manager_action_drafts import generate_room_change_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    old_room = event_entry.get("locked_room_id")
    new_room = payload.get("new_room")

    if not new_room:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.ROOM_CHANGE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="new_room is required",
        )

    # CAPTURE: Set room as LOCKED (manager selection = confirmed)
    # Also update room_eval_hash to match requirements_hash (room evaluation passed)
    req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        locked_room_id=new_room,
        room_eval_hash=req_hash,  # Mark room as evaluated
        offer_hash=None,  # Invalidate offer - needs regeneration with new room
    )

    # ADVANCE: Check what step we should be at now
    new_step = _determine_next_step(event_entry)
    workflow_advanced = new_step > current_step

    # Update current_step if advancing
    if new_step != current_step:
        update_event_metadata(event_entry, current_step=new_step)

    # Refresh gatekeeper
    gatekeeper = refresh_gatekeeper(event_entry)
    gates_satisfied = [k for k, v in gatekeeper.items() if v]

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        new_step,
        f"manager_room_set:{old_room}->{new_room}:locked=True",
        manager_id or "manager",
    )

    # Log activity
    log_workflow_activity(
        event_entry,
        "room_locked",
        room=new_room,
    )

    # Generate client notification
    notification_draft = generate_room_change_notification(
        event_entry, old_room, new_room
    )

    logger.info(
        "[MANAGER_ACTION] Room set to %s for event %s (locked=True, advancing to step %d)",
        new_room, event_id, new_step
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.ROOM_CHANGE,
        event_id=event_id,
        previous_step=current_step,
        new_step=new_step,
        workflow_advanced=workflow_advanced,
        needs_client_notification=True,
        notification_draft=notification_draft,
        gates_satisfied=gates_satisfied,
        details={
            "old_room": old_room,
            "new_room": new_room,
            "room_locked": True,
        },
    )


# =============================================================================
# ROOM CANCELLATION HANDLER
# =============================================================================


def _handle_manager_room_cancellation(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated room cancellation.

    This IS a detour case - removing a confirmed room requires client to select a new one.
    """
    from workflows.notifications.manager_action_drafts import generate_room_cancellation_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    old_room = event_entry.get("locked_room_id")
    reason = payload.get("reason", "")

    if not old_room:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.ROOM_CANCELLATION,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="No room is currently reserved",
        )

    # CLEAR room - this requires client to select a new one
    update_event_metadata(
        event_entry,
        locked_room_id=None,
        room_eval_hash=None,
        offer_hash=None,
        current_step=3,  # Back to room selection
        thread_state="Awaiting Client Response",
    )

    # Refresh gatekeeper (for consistency, even though we're routing to step 3)
    refresh_gatekeeper(event_entry)

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        3,
        f"manager_room_cancelled:{old_room}:{reason}",
        manager_id or "manager",
    )

    # Log activity
    log_workflow_activity(
        event_entry,
        "room_released",
        room=old_room,
    )

    # Generate client notification
    notification_draft = generate_room_cancellation_notification(
        event_entry, old_room, reason
    )

    logger.info(
        "[MANAGER_ACTION] Room %s cancelled for event %s (reason: %s)",
        old_room, event_id, reason
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.ROOM_CANCELLATION,
        event_id=event_id,
        previous_step=current_step,
        new_step=3,  # Client needs to select new room
        workflow_advanced=False,  # This is a step back, not advance
        needs_client_notification=True,
        notification_draft=notification_draft,
        details={
            "cancelled_room": old_room,
            "reason": reason,
        },
    )


# =============================================================================
# REQUIREMENTS UPDATE HANDLER
# =============================================================================


def _handle_manager_requirements_update(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated requirements update.

    CAPTURE-AND-ADVANCE:
    - Update requirements (participants, layout, etc.)
    - Recompute requirements_hash
    - If room still fits new requirements, keep it; otherwise may need re-evaluation
    - Invalidate offer_hash so offer regenerates with new details
    """
    from workflows.notifications.manager_action_drafts import generate_requirements_update_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    requirements = event_entry.get("requirements") or {}
    old_requirements = dict(requirements)

    # Extract fields from payload
    updates = {}
    if "participants" in payload or "number_of_participants" in payload:
        updates["number_of_participants"] = payload.get("participants") or payload.get("number_of_participants")
    if "layout" in payload or "seating_layout" in payload:
        updates["seating_layout"] = payload.get("layout") or payload.get("seating_layout")
    if "special_requirements" in payload:
        updates["special_requirements"] = payload.get("special_requirements")
    if "event_duration" in payload:
        updates["event_duration"] = payload.get("event_duration")

    if not updates:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.REQUIREMENTS_UPDATE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="No requirements fields provided",
        )

    # CAPTURE: Merge updates into requirements
    new_requirements = {**requirements, **updates}
    event_entry["requirements"] = new_requirements

    # Compute new requirements hash
    new_req_hash = requirements_hash(new_requirements)
    old_req_hash = event_entry.get("requirements_hash")

    # Update requirements_hash and invalidate offer (needs regeneration)
    update_event_metadata(
        event_entry,
        requirements_hash=new_req_hash,
        offer_hash=None,  # Invalidate - offer needs to reflect new requirements
    )

    # ADVANCE: Check what step we should be at now
    new_step = _determine_next_step(event_entry)
    workflow_advanced = new_step > current_step

    if new_step != current_step:
        update_event_metadata(event_entry, current_step=new_step)

    # Refresh gatekeeper
    gatekeeper = refresh_gatekeeper(event_entry)
    gates_satisfied = [k for k, v in gatekeeper.items() if v]

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        new_step,
        f"manager_requirements_update:{list(updates.keys())}",
        manager_id or "manager",
    )

    # Log activity
    if "number_of_participants" in updates:
        log_workflow_activity(
            event_entry,
            "participants_changed",
            old_count=str(old_requirements.get("number_of_participants", "not set")),
            new_count=str(updates["number_of_participants"]),
        )

    # Generate client notification
    notification_draft = generate_requirements_update_notification(
        event_entry, old_requirements, new_requirements
    )

    logger.info(
        "[MANAGER_ACTION] Requirements updated for event %s: %s (advancing to step %d)",
        event_id, updates, new_step
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.REQUIREMENTS_UPDATE,
        event_id=event_id,
        previous_step=current_step,
        new_step=new_step,
        workflow_advanced=workflow_advanced,
        needs_client_notification=True,
        notification_draft=notification_draft,
        gates_satisfied=gates_satisfied,
        details={
            "updates": updates,
            "old_hash": old_req_hash,
            "new_hash": new_req_hash,
        },
    )


# =============================================================================
# BILLING UPDATE HANDLER (Capture-and-Advance)
# =============================================================================


def _handle_manager_billing_update(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated billing information update.

    CAPTURE-AND-ADVANCE:
    - Capture billing details (company, address, etc.)
    - These satisfy the billing gate for Step 7
    - Check if all confirmation gates are now satisfied
    """
    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    # Extract billing fields
    event_data = event_entry.setdefault("event_data", {})
    captured = event_entry.setdefault("captured", {})
    billing = captured.setdefault("billing", {})

    # Update billing fields from payload
    if payload.get("company"):
        event_data["Company"] = payload["company"]
        billing["company"] = payload["company"]
    if payload.get("address") or payload.get("billing_address"):
        addr = payload.get("address") or payload.get("billing_address")
        event_data["Billing Address"] = addr
        billing["address"] = addr
    if payload.get("vat"):
        billing["vat"] = payload["vat"]
    if payload.get("email"):
        billing["email"] = payload["email"]

    # ADVANCE: Check what step we should be at now
    new_step = _determine_next_step(event_entry)
    workflow_advanced = new_step > current_step

    if new_step != current_step:
        update_event_metadata(event_entry, current_step=new_step)

    # Refresh gatekeeper
    gatekeeper = refresh_gatekeeper(event_entry)
    gates_satisfied = [k for k, v in gatekeeper.items() if v]

    # Check Step 7 readiness specifically
    step7_explain = explain_step7_gate(event_entry)

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        new_step,
        "manager_billing_update",
        manager_id or "manager",
    )

    # Log activity
    log_workflow_activity(
        event_entry,
        "billing_updated",
    )

    logger.info(
        "[MANAGER_ACTION] Billing updated for event %s (step7_ready=%s, advancing to step %d)",
        event_id, step7_explain["ready"], new_step
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.BILLING_UPDATE,
        event_id=event_id,
        previous_step=current_step,
        new_step=new_step,
        workflow_advanced=workflow_advanced,
        needs_client_notification=False,  # Billing is internal, no notification needed
        gates_satisfied=gates_satisfied,
        details={
            "step7_ready": step7_explain["ready"],
            "step7_missing": step7_explain.get("missing_now", []),
        },
    )


# =============================================================================
# OFFER UPDATE HANDLER
# =============================================================================


def _handle_manager_offer_update(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated offer update.

    Updates offer fields and marks for regeneration/resending.
    """
    from workflows.notifications.manager_action_drafts import generate_offer_update_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    # Get current offer info
    old_offer = event_entry.get("offer") or {}

    # Extract updates
    offer_updates = {}
    if "price" in payload or "total" in payload:
        offer_updates["total"] = payload.get("price") or payload.get("total")
    if "terms" in payload:
        offer_updates["terms"] = payload.get("terms")
    if "discount" in payload:
        offer_updates["discount"] = payload.get("discount")
    if "notes" in payload:
        offer_updates["notes"] = payload.get("notes")

    if not offer_updates:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.OFFER_UPDATE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="No offer fields provided",
        )

    # Merge updates
    new_offer = {**old_offer, **offer_updates}
    event_entry["offer"] = new_offer

    # Invalidate offer hash to force regeneration/resend
    # BUG FIX: Also clear offer_status - Step 7 gate uses offer_status, not offer_accepted
    # Without clearing offer_status, the gate can incorrectly report "ready"
    update_event_metadata(
        event_entry,
        offer_hash=None,
        offer_accepted=False,  # Client needs to accept new offer
        offer_status=None,  # Clear stale status (Step 7 gate uses this)
    )

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        current_step,
        "manager_offer_update",
        manager_id or "manager",
    )

    # Log activity
    if "total" in offer_updates:
        log_workflow_activity(
            event_entry,
            "price_updated",
            old_price=str(old_offer.get("total", "not set")),
            new_price=str(offer_updates["total"]),
        )

    # Generate client notification
    notification_draft = generate_offer_update_notification(
        event_entry, old_offer, new_offer
    )

    logger.info(
        "[MANAGER_ACTION] Offer updated for event %s: %s",
        event_id, offer_updates
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.OFFER_UPDATE,
        event_id=event_id,
        previous_step=current_step,
        new_step=current_step,  # Stay at current step, offer will be resent
        workflow_advanced=False,
        needs_client_notification=True,
        notification_draft=notification_draft,
        details={
            "updates": offer_updates,
            "offer_needs_resend": True,
        },
    )


# =============================================================================
# SITE VISIT RESCHEDULE HANDLER
# =============================================================================


def _handle_manager_site_visit_reschedule(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """
    Handle manager-initiated site visit reschedule.
    """
    from workflows.notifications.manager_action_drafts import generate_site_visit_reschedule_notification

    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    old_date = event_entry.get("site_visit_date")
    old_time = event_entry.get("site_visit_time")

    new_date = payload.get("new_date")
    new_time = payload.get("new_time")

    if not new_date and not new_time:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="new_date or new_time is required",
        )

    # Update site visit fields
    update_fields = {}
    if new_date:
        update_fields["site_visit_date"] = new_date
    if new_time:
        update_fields["site_visit_time"] = new_time

    update_event_metadata(event_entry, **update_fields)

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        current_step,
        f"manager_site_visit_reschedule:{new_date or old_date}_{new_time or old_time}",
        manager_id or "manager",
    )

    # Log activity
    log_workflow_activity(
        event_entry,
        "site_visit_booked",
        date=f"{new_date or old_date} {new_time or old_time or ''}".strip(),
    )

    # Generate client notification
    notification_draft = generate_site_visit_reschedule_notification(
        event_entry, old_date, old_time, new_date, new_time
    )

    logger.info(
        "[MANAGER_ACTION] Site visit rescheduled for event %s: %s %s -> %s %s",
        event_id, old_date, old_time, new_date, new_time
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
        event_id=event_id,
        previous_step=current_step,
        new_step=current_step,
        workflow_advanced=False,
        needs_client_notification=True,
        notification_draft=notification_draft,
        details={
            "old_date": old_date,
            "old_time": old_time,
            "new_date": new_date,
            "new_time": new_time,
        },
    )


# =============================================================================
# HIL APPROVE HANDLER
# =============================================================================


def _handle_manager_hil_approve(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """Handle manager HIL approval."""
    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    task_id = payload.get("task_id")
    modified_response = payload.get("modified_response")

    if not task_id:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.HIL_APPROVE,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="task_id is required",
        )

    # Log activity
    log_workflow_activity(
        event_entry,
        "hil_approved",
        step=str(current_step),
        task_type=payload.get("task_type", "message"),
    )

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        current_step,
        f"manager_hil_approve:{task_id}:modified={bool(modified_response)}",
        manager_id or "manager",
    )

    logger.info(
        "[MANAGER_ACTION] HIL approved for event %s task %s",
        event_id, task_id
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.HIL_APPROVE,
        event_id=event_id,
        previous_step=current_step,
        new_step=current_step,
        workflow_advanced=False,
        needs_client_notification=False,
        details={
            "task_id": task_id,
            "modified": bool(modified_response),
        },
    )


# =============================================================================
# HIL REJECT HANDLER
# =============================================================================


def _handle_manager_hil_reject(
    event_entry: Dict[str, Any],
    payload: Dict[str, Any],
    manager_id: Optional[str],
) -> ManagerActionResult:
    """Handle manager HIL rejection."""
    event_id = event_entry.get("event_id", "unknown")
    current_step = event_entry.get("current_step", 1)

    task_id = payload.get("task_id")
    reason = payload.get("reason", "")

    if not task_id:
        return ManagerActionResult(
            success=False,
            action_type=ManagerActionType.HIL_REJECT,
            event_id=event_id,
            previous_step=current_step,
            new_step=current_step,
            workflow_advanced=False,
            needs_client_notification=False,
            error="task_id is required",
        )

    # Log activity
    log_workflow_activity(
        event_entry,
        "hil_rejected",
        step=str(current_step),
        reason=reason,
    )

    # Audit entry
    append_audit_entry(
        event_entry,
        current_step,
        current_step,
        f"manager_hil_reject:{task_id}:{reason}",
        manager_id or "manager",
    )

    logger.info(
        "[MANAGER_ACTION] HIL rejected for event %s task %s (reason: %s)",
        event_id, task_id, reason
    )

    return ManagerActionResult(
        success=True,
        action_type=ManagerActionType.HIL_REJECT,
        event_id=event_id,
        previous_step=current_step,
        new_step=current_step,
        workflow_advanced=False,
        needs_client_notification=False,
        details={
            "task_id": task_id,
            "reason": reason,
        },
    )


__all__ = [
    "ManagerActionType",
    "ManagerActionResult",
    "process_manager_action",
]
