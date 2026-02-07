"""Event bootstrap module - handles new vs reuse event decision.

This module contains the logic for determining whether to create a new event
record or reuse an existing one based on:
- Email thread resolution (reply headers, LLM semantic matching)
- Date differences (new inquiry vs date change)
- Terminal states (confirmed, completed, cancelled)
- Offer accepted status (with billing/deposit continuation)
- Site visit status (terminal vs mid-flow)

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from workflows.common.types import WorkflowState
from workflows.common.timeutils import format_ts_to_ddmmyyyy
from workflows.io.database import (
    create_event_entry,
    default_event_record,
    find_event_idx_by_id,
    last_event_for_email,
    update_event_entry,
    update_event_metadata,
)
from detection.keywords.buckets import has_revision_signal
from debug.hooks import trace_db_write

from .gate_confirmation import looks_like_billing_fragment as _looks_like_billing_fragment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Email Thread Resolution (Layer 1 + Layer 2)
# ---------------------------------------------------------------------------

def _has_email_headers(message_payload: Dict[str, Any]) -> bool:
    """Check if message has email headers for thread resolution."""
    headers = message_payload.get("headers", {})
    # Check for common email headers that indicate this came from email
    return bool(
        headers.get("Message-ID") or
        headers.get("message_id") or
        headers.get("In-Reply-To") or
        headers.get("in_reply_to") or
        headers.get("References") or
        headers.get("references")
    )


def _extract_email_headers(message_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract email headers from message payload for reply detection."""
    headers = message_payload.get("headers", {})
    return {
        "Message-ID": headers.get("Message-ID") or headers.get("message_id"),
        "In-Reply-To": headers.get("In-Reply-To") or headers.get("in_reply_to"),
        "References": headers.get("References") or headers.get("references"),
        "body": message_payload.get("body", ""),
    }


def _resolve_email_thread(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    thread_id: str,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Resolve email thread using Layer 1 (headers) and Layer 2 (LLM).

    Returns:
        Tuple of (event_entry or None, was_resolved: bool)
        - If resolved, returns the event entry to attach to
        - If not resolved, returns (None, False) to fall through to existing logic
    """
    from workflows.io.email_threading import (
        is_reply,
        link_reply_to_thread,
        store_email_message,
        ThreadResolver,
    )

    headers = _extract_email_headers(message_payload)
    message_id = headers.get("Message-ID") or message_payload.get("msg_id", "")

    # Layer 1: Reply Detection (NO LLM)
    is_reply_msg, parent_id = is_reply(headers)

    if is_reply_msg and parent_id:
        event_id = link_reply_to_thread(
            parent_id,
            state.db.get("email_messages", []),
            state.db.get("thread_mappings", []),
        )
        if event_id:
            # Found parent - attach to that event
            idx = find_event_idx_by_id(state.db, event_id)
            if idx is not None:
                event_entry = state.db["events"][idx]
                # Store this message for future reply detection
                store_email_message(
                    state.db,
                    message_id=message_id,
                    from_address=state.client_id or "",
                    resolved_event_id=event_id,
                    in_reply_to=headers.get("In-Reply-To"),
                    references=headers.get("References") if isinstance(headers.get("References"), list) else None,
                )
                trace_db_write(thread_id, "Step1_Intake", "thread_resolved_layer1", {
                    "event_id": event_id,
                    "parent_id": parent_id,
                    "method": "reply_headers",
                })
                logger.info("[STEP1][THREAD] Layer 1 resolved reply to event %s via %s", event_id, parent_id)
                return event_entry, True

    # Layer 2: Thread Resolver (LLM) - only for NEW emails (not replies)
    if not is_reply_msg:
        resolver = ThreadResolver()
        result = resolver.resolve(
            email_from=state.client_id or "",
            email_subject=message_payload.get("subject", ""),
            email_body=message_payload.get("body", ""),
            db=state.db,
            message_id=message_id,
        )

        if result.decision == "attach" and result.event_id:
            idx = find_event_idx_by_id(state.db, result.event_id)
            if idx is not None:
                event_entry = state.db["events"][idx]
                # Store this message for future reply detection
                store_email_message(
                    state.db,
                    message_id=message_id,
                    from_address=state.client_id or "",
                    resolved_event_id=result.event_id,
                )
                trace_db_write(thread_id, "Step1_Intake", "thread_resolved_layer2", {
                    "event_id": result.event_id,
                    "confidence": result.confidence,
                    "reason": result.reason,
                })
                logger.info("[STEP1][THREAD] Layer 2 attached to event %s (confidence=%.2f)",
                            result.event_id, result.confidence)
                return event_entry, True

        # Log possible duplicates for manual review
        if result.possible_duplicates:
            trace_db_write(thread_id, "Step1_Intake", "thread_possible_duplicates", {
                "possible_duplicates": result.possible_duplicates,
                "reason": result.reason,
            })
            logger.info("[STEP1][THREAD] Possible duplicates flagged: %s", result.possible_duplicates)

    # Thread resolution didn't find a match - fall through to existing logic
    return None, False


def _store_initial_email_message(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    event_id: str,
) -> None:
    """Store initial email message for future reply detection.

    Called when a new event is created to record the first message
    in the thread, enabling future replies to be linked.
    """
    if not _has_email_headers(message_payload):
        return

    from workflows.io.email_threading import store_email_message, create_thread_mapping

    headers = _extract_email_headers(message_payload)
    message_id = headers.get("Message-ID") or message_payload.get("msg_id", "")

    if message_id:
        store_email_message(
            state.db,
            message_id=message_id,
            from_address=state.client_id or "",
            resolved_event_id=event_id,
            in_reply_to=headers.get("In-Reply-To"),
            references=headers.get("References") if isinstance(headers.get("References"), list) else None,
        )
        # Also create a thread mapping for quick lookup
        create_thread_mapping(state.db, message_id, event_id)


def _thread_id(state: WorkflowState) -> str:
    """Get thread ID for tracing."""
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"


# Pattern to detect deposit/payment date mentions
_DEPOSIT_DATE_PATTERN = re.compile(
    r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|'
    r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
    re.IGNORECASE
)


def ensure_event_record(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Create or refresh the event record for the intake step.

    This function decides whether to:
    1. Create a brand new event (no prior event, terminal state, or genuinely new inquiry)
    2. Reuse and update an existing event (continuation of conversation)

    Decision factors:
    - Different date = new inquiry UNLESS revision signal detected (date change)
    - Terminal status (confirmed/completed/cancelled) = new event
    - Offer accepted = new event UNLESS billing/deposit follow-up or revision
    - Site visit terminal (completed/declined/no_show) = new event

    Args:
        state: Current workflow state
        message_payload: Raw message data
        user_info: Extracted user information from LLM

    Returns:
        The event_entry dict (either newly created or updated existing)
    """
    thread_id = _thread_id(state)
    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    event_data = default_event_record(user_info, message_payload, received_date)

    # ---------------------------------------------------------------------------
    # NEW: Email Thread Resolution (runs BEFORE existing lookup logic)
    # ---------------------------------------------------------------------------
    # If message has email headers, try to resolve thread via:
    #   Layer 1: Reply detection using In-Reply-To/References headers (no LLM)
    #   Layer 2: LLM semantic matching for new emails
    if _has_email_headers(message_payload):
        resolved_event, was_resolved = _resolve_email_thread(state, message_payload, thread_id)
        if was_resolved and resolved_event:
            # Thread resolution found the event - update it and return
            idx = find_event_idx_by_id(state.db, resolved_event["event_id"])
            if idx is not None:
                state.updated_fields = update_event_entry(state.db, idx, event_data)
                event_entry = state.db["events"][idx]
                if not event_entry.get("thread_id"):
                    event_entry["thread_id"] = thread_id
                trace_db_write(
                    thread_id,
                    "Step1_Intake",
                    "db.events.update_via_thread_resolution",
                    {"event_id": event_entry.get("event_id"), "updated": list(state.updated_fields)},
                )
                update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
                return event_entry
    # ---------------------------------------------------------------------------

    last_event = last_event_for_email(state.db, state.client_id or "")
    if not last_event:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        event_entry["thread_id"] = thread_id
        trace_db_write(thread_id, "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        # Store email message for future reply detection (if has headers)
        _store_initial_email_message(state, message_payload, event_entry["event_id"])
        return event_entry

    # Determine if we should create a NEW event instead of reusing
    should_create_new = False
    new_event_date = event_data.get("Event Date")
    existing_event_date = last_event.get("chosen_date") or (last_event.get("event_data") or {}).get("Event Date")

    # Check for actual dates (not placeholder values)
    placeholder_values = ("Not specified", "not specified", None, "")
    new_date_is_actual = new_event_date and new_event_date not in placeholder_values
    existing_date_is_actual = existing_event_date and existing_event_date not in placeholder_values

    # Check for date change vs new inquiry signals
    message_text = (state.message.body or "") + " " + (state.message.subject or "")
    is_date_change_request = has_revision_signal(message_text)
    is_deposit_payment_date = bool(message_text and _DEPOSIT_DATE_PATTERN.search(message_text))

    # GUARD: Skip date change logic when site visit flow is active
    from workflows.common.site_visit_state import is_site_visit_active
    site_visit_active_for_new_check = is_site_visit_active(last_event)

    if new_date_is_actual and existing_date_is_actual and new_event_date != existing_event_date:
        if site_visit_active_for_new_check:
            # Site visit is active - date is for site visit, not event date change
            logger.info("[STEP1][SV_GUARD] Site visit active - skipping date change/new event logic")
        elif is_date_change_request or is_deposit_payment_date:
            # This is a date CHANGE on existing event - don't create new event
            trace_db_write(thread_id, "Step1_Intake", "date_change_detected", {
                "reason": "date_change_request",
                "old_date": existing_event_date,
                "new_date": new_event_date,
            })
            logger.info("[STEP1][DATE_CHANGE] Detected date change from %s to %s, will route via detour",
                        existing_event_date, new_event_date)
        else:
            # Genuine NEW inquiry with a different date
            should_create_new = True
            trace_db_write(thread_id, "Step1_Intake", "new_event_decision", {
                "reason": "different_date",
                "new_date": new_event_date,
                "existing_date": existing_event_date,
            })

    # Terminal states - don't reuse
    existing_status = last_event.get("status", "").lower()
    if existing_status in ("confirmed", "completed", "cancelled"):
        should_create_new = True
        trace_db_write(thread_id, "Step1_Intake", "new_event_decision", {
            "reason": "terminal_status",
            "status": existing_status,
        })

    # Offer already accepted - check if continuation or new inquiry
    if last_event.get("offer_accepted"):
        should_create_new = _should_create_new_after_offer_accepted(
            state, last_event, message_text, thread_id
        )

    # Site visit terminal states - create new event for new inquiries
    visit_state = last_event.get("site_visit_state") or {}
    visit_status = visit_state.get("status")
    if visit_status in ("completed", "declined", "no_show"):
        should_create_new = True
        trace_db_write(thread_id, "Step1_Intake", "new_event_decision", {
            "reason": f"site_visit_{visit_status}",
        })

    if should_create_new:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        event_entry["thread_id"] = thread_id
        trace_db_write(thread_id, "Step1_Intake", "db.events.create", {
            "event_id": event_entry.get("event_id"),
            "reason": "new_inquiry_detected",
        })
        # Store email message for future reply detection (if has headers)
        _store_initial_email_message(state, message_payload, event_entry["event_id"])
        return event_entry

    # Reuse existing event
    idx = find_event_idx_by_id(state.db, last_event["event_id"])
    if idx is None:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        event_entry["thread_id"] = thread_id
        trace_db_write(thread_id, "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        # Store email message for future reply detection (if has headers)
        _store_initial_email_message(state, message_payload, event_entry["event_id"])
        return event_entry

    state.updated_fields = update_event_entry(state.db, idx, event_data)
    event_entry = state.db["events"][idx]
    if not event_entry.get("thread_id"):
        event_entry["thread_id"] = thread_id
    trace_db_write(
        thread_id,
        "Step1_Intake",
        "db.events.update",
        {"event_id": event_entry.get("event_id"), "updated": list(state.updated_fields)},
    )
    update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
    return event_entry


def _should_create_new_after_offer_accepted(
    state: WorkflowState,
    last_event: Dict[str, Any],
    message_text: str,
    thread_id: str,
) -> bool:
    """Determine if a new event should be created after offer was accepted.

    Returns False (continue with existing event) if this is:
    - Billing info follow-up
    - Deposit payment follow-up
    - Revision/change request on accepted offer
    - Message with matching event_id

    Returns True (create new event) if this is a genuinely new inquiry.
    """
    billing_reqs = last_event.get("billing_requirements") or {}
    awaiting_billing = billing_reqs.get("awaiting_billing_for_accept", False)
    deposit_info = last_event.get("deposit_info") or {}
    awaiting_deposit = deposit_info.get("deposit_required") and not deposit_info.get("deposit_paid")

    # Check if message looks like billing info
    message_body = (state.message.body or "").strip().lower()
    looks_like_billing = _looks_like_billing_fragment(message_body) if message_body else False

    # Check for synthetic deposit payment notification
    deposit_just_paid = state.message.extras.get("deposit_just_paid", False)

    # Check if message includes explicit event_id matching this event
    msg_event_id = state.message.extras.get("event_id")
    event_id_matches = msg_event_id and msg_event_id == last_event.get("event_id")

    # Check if this is a revision/change request
    is_revision_message = has_revision_signal(message_text)

    # Continue with existing event if any continuation signal
    if awaiting_billing or awaiting_deposit or looks_like_billing or deposit_just_paid or event_id_matches or is_revision_message:
        trace_db_write(thread_id, "Step1_Intake", "offer_accepted_continue", {
            "reason": "billing_or_deposit_or_revision_followup",
            "awaiting_billing": awaiting_billing,
            "awaiting_deposit": awaiting_deposit,
            "looks_like_billing": looks_like_billing,
            "deposit_just_paid": deposit_just_paid,
            "event_id_matches": event_id_matches,
            "is_revision_message": is_revision_message,
        })
        return False

    # New inquiry from same client after offer was accepted
    trace_db_write(thread_id, "Step1_Intake", "new_event_decision", {
        "reason": "offer_already_accepted",
        "event_id": last_event.get("event_id"),
    })
    return True
