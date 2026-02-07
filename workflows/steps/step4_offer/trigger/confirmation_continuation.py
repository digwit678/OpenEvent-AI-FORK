"""Confirmation continuation handler for Step 4.

Handles BUG-053 stale ``offer_accepted`` clearing, the unified
confirmation gate check, deposit reload, and HIL routing.
Returns a ``GroupResult`` when halting, or ``None`` to continue.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult, WorkflowState
from workflows.common.confirmation_gate import auto_continue_if_ready, get_next_prompt
from workflows.io.database import update_event_metadata

logger = logging.getLogger(__name__)


def handle_confirmation_continuation(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
) -> Optional[GroupResult]:
    """Check confirmation prerequisites and route to HIL if ready.

    This covers:
    1. Stale ``offer_accepted`` clearing (detour fix + BUG-053)
    2. Confirmation gate: billing + deposit checks
    3. Deposit reload from DB (frontend API payments)
    4. HIL acceptance flow routing

    Returns ``GroupResult`` with ``halt=True`` when waiting on prerequisites
    or routed to HIL.  Returns ``None`` when no ``offer_accepted`` flag is set
    and normal processing should continue.
    """
    from .helpers import _start_hil_acceptance_flow

    event_id = event_entry.get("event_id")

    # DETOUR FIX: If we came from a detour (caller_step is set), we need to regenerate
    # the offer even if the previous one was accepted.
    caller_step = event_entry.get("caller_step")
    if caller_step is not None and event_entry.get("offer_accepted"):
        logger.info("[Step4] Detour in progress (caller=%s) - clearing offer_accepted to regenerate offer", caller_step)
        event_entry["offer_accepted"] = False
        state.extras["persist"] = True

    # BUG-053 FIX: When entering Step 4 from an earlier step (e.g. Step 3 after
    # room confirmation), any previous offer_accepted flag is stale and must be
    # cleared so a fresh offer is generated.
    if previous_step < 4 and event_entry.get("offer_accepted"):
        logger.info(
            "[Step4] Entering from step %s — clearing stale offer_accepted to regenerate offer",
            previous_step,
        )
        event_entry["offer_accepted"] = False
        state.extras["persist"] = True

    if not (event_id and event_entry.get("offer_accepted")):
        return None

    from workflows.common.confirmation_gate import check_confirmation_gate

    # First check in-memory state (has latest billing)
    gate_status = check_confirmation_gate(event_entry)

    # If deposit is required but not paid in memory, check database for API updates
    if gate_status.deposit_required and not gate_status.deposit_paid:
        _, db_status, fresh_entry = auto_continue_if_ready(event_id, event_entry)
        if db_status.deposit_paid:
            gate_status = db_status
            event_entry["deposit_info"] = fresh_entry.get("deposit_info", {})
            event_entry["deposit_state"] = fresh_entry.get("deposit_state", {})

    if gate_status.ready_for_hil:
        logger.debug(
            "[Step4] Confirmation gate passed: billing_complete=%s, deposit_required=%s, deposit_paid=%s",
            gate_status.billing_complete, gate_status.deposit_required, gate_status.deposit_paid,
        )
        return _start_hil_acceptance_flow(
            state, event_entry, previous_step, thread_id,
            audit_label="offer_accept_pending_hil_gate_passed",
            action="offer_accept_pending_hil",
        )

    # Not ready — prompt for missing items
    next_prompt = get_next_prompt(gate_status, step=4)
    if next_prompt:
        state.add_draft_message(next_prompt)
        update_event_metadata(event_entry, current_step=4, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        state.extras["persist"] = True
        return GroupResult(
            action="awaiting_prerequisites",
            payload={
                "pending": gate_status.pending_items,
                "billing_complete": gate_status.billing_complete,
                "deposit_paid": gate_status.deposit_paid,
            },
            halt=True,
        )

    return None
