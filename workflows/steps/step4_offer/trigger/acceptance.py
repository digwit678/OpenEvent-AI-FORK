"""Offer acceptance handling for Step 4.

Detects acceptance patterns, checks billing/deposit gates, and routes
to HIL when all prerequisites are met.
Returns ``GroupResult`` when the acceptance is handled, or ``None``
to continue normal processing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult, WorkflowState
from workflows.common.billing_gate import (
    refresh_billing,
    flag_billing_accept_pending,
    billing_prompt_draft,
)
from workflows.io.database import append_audit_entry, update_event_metadata
from debug.trace import set_hil_open

logger = logging.getLogger(__name__)


def handle_offer_acceptance(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    normalized_message_text: str,
    user_info: Dict[str, Any],
    previous_step: int,
    thread_id: str,
) -> Optional[GroupResult]:
    """Check for offer acceptance and route through billing/deposit/HIL gates.

    Guards:
    - Room-choice signals (``_room_choice_detected``, "proceed with room")
      suppress acceptance detection to avoid false positives.

    Returns ``GroupResult`` when acceptance is detected and handled,
    or ``None`` when no acceptance was found and processing should continue.
    """
    from .helpers import _looks_like_offer_acceptance, _start_hil_acceptance_flow

    # Guard: ignore room-selection clicks (labels like "Proceed with Room E")
    room_choice_signal = bool(user_info.get("_room_choice_detected"))
    room_selection_phrase = "proceed with room" in (normalized_message_text or "").lower()
    acceptance_applicable = not (room_choice_signal or room_selection_phrase)

    if not (acceptance_applicable and _looks_like_offer_acceptance(normalized_message_text)):
        return None

    # Mark offer as accepted so we can continue after deposit payment
    event_entry["offer_accepted"] = True
    state.extras["persist"] = True

    billing_missing = refresh_billing(event_entry)
    if billing_missing:
        flag_billing_accept_pending(event_entry, billing_missing)
        prompt = billing_prompt_draft(billing_missing, step=4)
        state.add_draft_message(prompt)
        append_audit_entry(event_entry, previous_step, 4, "offer_accept_blocked_missing_billing")
        update_event_metadata(
            event_entry,
            current_step=5,
            thread_state="Awaiting Client",
            transition_ready=False,
            caller_step=None,
        )
        state.current_step = 5
        state.caller_step = None
        state.set_thread_state("Awaiting Client")
        set_hil_open(thread_id, False)
        state.extras["persist"] = True

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "missing": billing_missing,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="offer_accept_requires_billing", payload=payload, halt=True)

    # Check if deposit is required but not paid
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_required = deposit_info.get("deposit_required", False)
    deposit_paid = deposit_info.get("deposit_paid", False)
    deposit_amount = deposit_info.get("deposit_amount", 0)

    if deposit_required and not deposit_paid and deposit_amount > 0:
        deposit_reminder = {
            "body_markdown": (
                f"Thank you for wanting to confirm! Before I can proceed with your booking, "
                f"please complete the deposit payment of CHF {deposit_amount:,.2f}. "
                f"Once the deposit is received, I'll finalize your booking. "
                f"You can pay the deposit using the payment option shown in the offer."
            ),
            "step": 4,
            "topic": "deposit_reminder",
            "next_step": "Awaiting deposit payment",
            "thread_state": "Awaiting Client",
            "requires_approval": False,
        }
        state.add_draft_message(deposit_reminder)
        append_audit_entry(event_entry, previous_step, 4, "offer_accept_blocked_deposit_unpaid")
        update_event_metadata(
            event_entry,
            current_step=4,
            thread_state="Awaiting Client",
            transition_ready=False,
        )
        state.current_step = 4
        state.set_thread_state("Awaiting Client")
        set_hil_open(thread_id, False)
        state.extras["persist"] = True

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "deposit_required": deposit_amount,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="offer_accept_requires_deposit", payload=payload, halt=True)

    # Always route acceptances through HIL so the manager dashboard shows the approval buttons.
    return _start_hil_acceptance_flow(
        state,
        event_entry,
        previous_step,
        thread_id,
        audit_label="offer_accept_pending_hil",
        action="offer_accept_pending_hil",
    )
