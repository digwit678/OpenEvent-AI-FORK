"""Internal helper functions for the Step 4 offer handler.

Moved from ``step4_handler.py`` during CQ-3 god-function refactoring.
These are utility / presentation helpers — no workflow orchestration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult, WorkflowState
from workflows.common.billing import format_billing_display
from workflows.common.prompts import append_footer
from workflows.common.site_visit_state import is_site_visit_scheduled
from workflows.common.room_rules import site_visit_allowed
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    present_general_room_qna,
)
from workflows.io.database import append_audit_entry, update_event_metadata
# MIGRATED: from workflows.nlu.semantic_matchers -> backend.detection.response.matchers
from detection.response.matchers import matches_acceptance_pattern
from detection.intent.confidence import check_nonsense_gate
from debug.trace import set_hil_open
from workflows.steps.step5_negotiation import _handle_accept, _offer_summary_lines as _hil_offer_summary_lines

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _strip_system_subject(subject: str) -> str:
    """Strip system-generated metadata from subject lines.

    The API adds "Client follow-up (YYYY-MM-DD HH:MM)" to follow-up messages.
    This timestamp should NOT be used for change detection as it would incorrectly
    trigger DATE change detection due to the timestamp in the subject.
    """
    import re
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state, stripping system-generated subject prefixes."""
    message = state.message
    if not message:
        return ""
    subject = _strip_system_subject(message.subject or "")
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _normalize_quotes(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u00b4": "'",
        "`": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for bad, repl in replacements.items():
        text = text.replace(bad, repl)
    return text


def _looks_like_offer_acceptance(message_text: str) -> bool:
    normalized = _normalize_quotes(message_text or "").lower()
    is_match, confidence, _ = matches_acceptance_pattern(normalized)
    return is_match and confidence > 0.5


# ---------------------------------------------------------------------------
# Nonsense gate
# ---------------------------------------------------------------------------

def handle_nonsense_gate(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    message_text: str,
) -> Optional[GroupResult]:
    """Check for off-topic/nonsense using existing confidence.

    Returns a ``GroupResult`` with ``halt=True`` for ignore/hil,
    or ``None`` to continue normal processing.
    """
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        return GroupResult(
            action="nonsense_ignored",
            payload={"reason": "low_confidence_no_workflow_signal", "step": 4},
            halt=True,
        )
    if nonsense_action == "hil":
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=4,
                next_step=4,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=4, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 4},
            halt=True,
        )
    return None


# ---------------------------------------------------------------------------
# Dead / rarely-used helpers (moved for completeness, annotated)
# ---------------------------------------------------------------------------

def _manager_request_detected(state: WorkflowState, event_entry: Dict[str, Any]) -> bool:
    """Detect explicit manager/special-request signals.

    NOTE: Potentially dead code as of CQ-3 refactoring (no callers found).
    Moved here to keep step4_handler clean. Verify before removing.
    """
    if (event_entry.get("flags") or {}).get("manager_requested"):
        return True
    text = (_message_text(state) or "").lower()
    manager_tokens = (
        "manager", "boss", "owner", "director", "gm",
        "general manager", "approve with manager", "manager approval",
    )
    if any(token in text for token in manager_tokens):
        flags = event_entry.setdefault("flags", {})
        flags["manager_requested"] = True
        state.extras["persist"] = True
        return True
    return False


def _auto_confirm_without_hil(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
) -> GroupResult:
    """Auto-confirm offer without HIL review.

    NOTE: Potentially dead code as of CQ-3 refactoring (no callers found).
    Moved here to keep step4_handler clean. Verify before removing.
    """
    offers = event_entry.get("offers") or []
    current_offer_id = event_entry.get("current_offer_id")
    summary_lines = _hil_offer_summary_lines(event_entry, include_cta=False)
    room_label = event_entry.get("locked_room_id") or event_entry.get("selected_room") or "the room"
    display_date = event_entry.get("chosen_date") or ""
    billing_display = format_billing_display(
        event_entry.get("billing_details") or {},
        (event_entry.get("event_data") or {}).get("Billing Address"),
    )

    body_lines = [f"Confirmed: {room_label} on {display_date} is locked in."]
    if billing_display:
        body_lines.append(f"Billing address: {billing_display}.")
    body_lines.append("")
    body_lines.append("\n".join(summary_lines))
    body_lines.append("")
    if is_site_visit_scheduled(event_entry):
        sv_state = event_entry.get("site_visit_state") or {}
        sv_date = sv_state.get("date_iso", "")
        sv_time = sv_state.get("time_slot", "")
        sv_display = f"{sv_date} at {sv_time}" if sv_time else sv_date
        body_lines.append(
            f"Your site visit is already scheduled for {sv_display}. "
            "We'll finalize the details closer to your event date."
        )
    else:
        if site_visit_allowed(event_entry):
            body_lines.append("Next step: let's line up a site visit. Do you have preferred dates or times?")
        else:
            body_lines.append("Next step: let me know any questions before we finalize the booking.")
    body = "\n".join(line for line in body_lines if line)

    draft = {
        "body": append_footer(body, step=5, next_step=5, thread_state="In Progress"),
        "step": 5,
        "topic": "negotiation_accept_no_hil",
        "requires_approval": False,
    }
    for offer in offers:
        if offer.get("offer_id") == current_offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    event_entry["offer_status"] = "Accepted"
    event_entry["negotiation_pending_decision"] = None
    event_entry["pending_hil_requests"] = []
    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="In Progress",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("In Progress")
    set_hil_open(thread_id, False)
    state.add_draft_message(draft)
    append_audit_entry(event_entry, previous_step, 5, "offer_accept_no_hil")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_accept_no_hil", payload=payload, halt=True)


def _start_hil_acceptance_flow(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
    *,
    audit_label: str,
    action: str,
) -> GroupResult:
    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    negotiation_state["counter_count"] = 0

    response = _handle_accept(event_entry)
    state.add_draft_message(response["draft"])
    append_audit_entry(event_entry, previous_step, 5, audit_label)
    event_entry["negotiation_pending_decision"] = response["pending"]
    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="Waiting on HIL",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("Waiting on HIL")
    set_hil_open(thread_id, True)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": response["offer_id"],
        "pending_decision": response["pending"],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action=action, payload=payload, halt=True)


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 4 - delegates to shared implementation."""
    return present_general_room_qna(
        state, event_entry, classification, thread_id,
        step_number=4, step_name="Offer",
    )


def _append_deferred_general_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> None:
    pre_count = len(state.draft_messages)
    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        return
    appended = append_general_qna_to_primary(state)
    if not appended:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
