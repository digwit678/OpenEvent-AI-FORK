"""
Cancellation handler for client-initiated full event cancellation.

Detects when a client wants to cancel their ENTIRE booking (not just a room,
product, or site visit change) and performs a hard-delete of the event record,
freeing the date/room for other bookings.

Detection strategy (LLM-First Rule):
- Primary: Trust LLM is_cancellation signal from unified detection
- Guards: Never trigger if is_change_request or is_site_visit_change is set
- Fallback: Keyword detection ONLY when LLM is completely unavailable (None)

See docs/plans/OPEN_DECISIONS.md DECISION-012 for design context.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from detection.unified import UnifiedDetectionResult
from workflows.common.types import GroupResult, WorkflowState

logger = logging.getLogger(__name__)


def is_cancellation_intent(
    detection: Optional[UnifiedDetectionResult],
    message_text: str,
) -> bool:
    """Determine if the message is a full event cancellation request.

    LLM-first (primary path):
    - detection.is_cancellation == True → True
    - detection.is_cancellation == False → False (trust LLM)

    Safety guards (prevent partial-cancel confusion):
    - is_change_request or is_site_visit_change → False
    - is_acceptance or is_confirmation → False

    Keyword fallback (only when LLM unavailable):
    - detection is None → use keyword detection with strong-only threshold

    Args:
        detection: Unified detection result (None if LLM completely failed)
        message_text: Raw message text (for keyword fallback)

    Returns:
        True if this is definitely a full event cancellation request
    """
    # LLM available: trust its semantic judgment
    if detection is not None:
        # Contradiction safety: acceptance/confirmation genuinely conflict
        # with cancellation — err on the safe side (don't cancel).
        if detection.is_acceptance or detection.is_confirmation:
            return False

        # Explicit cancellation signal takes priority over change_request.
        # Some LLMs co-set is_change_request alongside is_cancellation for
        # messages like "cancel the event" — the more-specific cancel wins.
        if detection.is_cancellation:
            return True

        # Safety guards: partial changes are never full cancellations
        if detection.is_change_request or detection.is_site_visit_change:
            return False

        # Q&A guard: "what's the cancellation policy?" is a question, not a cancel
        if detection.is_question:
            return False

        return False

    # LLM completely unavailable: keyword fallback with high threshold
    from detection.special.cancellation import detect_cancellation_intent
    is_cancel, confidence, _ = detect_cancellation_intent(message_text)
    # Only trust strong signals (>= 0.9) to avoid false positives
    return is_cancel and confidence >= 0.9


def handle_cancellation(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    detection: Optional[UnifiedDetectionResult],
) -> GroupResult:
    """Handle full event cancellation with immediate hard-delete.

    Steps:
    1. Log activity BEFORE delete (audit trail)
    2. Check deposit state for refund notice
    3. Hard-delete the event and all related records
    4. Build farewell draft message
    5. Create HIL task so manager sees it
    6. Return GroupResult with halt=True

    Args:
        state: Current workflow state
        event_entry: The event being cancelled
        detection: Detection result (for context)

    Returns:
        GroupResult with action="event_cancelled_deleted" and halt=True
    """
    from activity.persistence import log_workflow_activity
    from domain import TaskType
    from workflows.common.prompts import append_footer
    from workflows.io.database import delete_event, save_db, lock_path_for
    from workflows.io.tasks import enqueue_task

    event_id: str = event_entry.get("event_id", "")
    if not event_id:
        raise ValueError("Cannot cancel event without event_id")
    client_email = (event_entry.get("event_data", {}).get("Email") or "").lower()
    current_step = event_entry.get("current_step", 1)

    # 1. Log activity BEFORE delete (event_entry is gone after delete)
    log_workflow_activity(event_entry, "status_cancelled", reason="Client request")

    # 2. Check deposit state for refund notice
    deposit_state = event_entry.get("deposit_state", {})
    deposit_paid = deposit_state.get("status") == "paid"

    # 3. Hard-delete the event
    summary = delete_event(state.db, event_id)
    logger.info("[CANCELLATION] Hard-deleted event %s at step %s", event_id, current_step)

    # 4. Build farewell draft
    farewell_body = (
        "Your event has been cancelled. The date and room have been released."
    )
    if deposit_paid:
        farewell_body += (
            " We note that a deposit was paid — our team will follow up "
            "regarding the refund process."
        )
    farewell_body += (
        " We'd be happy to assist with any future events."
    )

    draft = {
        "body": append_footer(
            farewell_body,
            step=current_step,
            next_step="Close booking",
            thread_state="Closed",
            topic="cancellation",
        ),
        "step": current_step,
        "topic": "cancellation",
        "requires_approval": False,
    }
    state.add_draft_message(draft)

    # 5. Create HIL task so manager sees the cancellation
    task_payload = {
        "snippet": f"Client cancelled event at step {current_step}",
        "thread_id": state.thread_id,
        "step_id": current_step,
        "reason": "client_cancellation",
        "event_summary": {
            "email": client_email,
            "chosen_date": summary.get("chosen_date"),
            "locked_room": summary.get("locked_room_id"),
            "previous_step": current_step,
            "deposit_paid": deposit_paid,
        },
    }
    task_id = enqueue_task(
        state.db,
        TaskType.CANCELLATION_REQUEST,
        client_email,
        event_id,
        task_payload,
    )

    # Persist after delete + task creation
    save_db(state.db, state.db_path, lock_path_for(state.db_path))

    # 6. Clear event_entry from state (it's deleted)
    state.event_entry = None

    logger.info(
        "[CANCELLATION] Completed: event=%s, task=%s, deposit_paid=%s",
        event_id, task_id, deposit_paid,
    )

    return GroupResult(
        action="event_cancelled_deleted",
        halt=True,
        payload={
            "event_id": event_id,
            "task_id": task_id,
            "deposit_paid": deposit_paid,
            "summary": summary,
        },
    )
