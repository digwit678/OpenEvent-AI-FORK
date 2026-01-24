"""Manual review gate module.

This module handles the decision logic for when to route messages to
manual review (HIL) or handle standalone Q&A without an event.

Decision factors:
- Intent classification (event_request vs other)
- Confidence threshold (< 0.85 triggers review)
- Existing event context (step > 1 skips review)
- Awaiting billing state
- Gate confirmation detection
- Room choice detection
- Billing fragment detection
- Standalone Q&A handling

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from domain import IntentLabel
from workflows.common.prompts import append_footer
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from detection.intent.classifier import _detect_qna_types
from workflows.qna.router import generate_hybrid_qna_response

from .gate_confirmation import looks_like_billing_fragment as _looks_like_billing_fragment
from .confirmation_parsing import (
    extract_confirmation_details as _extract_confirmation_details,
    looks_like_gate_confirmation as _looks_like_gate_confirmation,
)
from .room_detection import detect_room_choice as _detect_room_choice
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from ..condition.checks import is_event_request

logger = logging.getLogger(__name__)


class GateDecision(Enum):
    """Decision from the manual review gate."""
    CONTINUE = "continue"  # Continue with normal processing
    MANUAL_REVIEW = "manual_review"  # Route to HIL
    STANDALONE_QNA = "standalone_qna"  # Handle as standalone Q&A


@dataclass
class ManualReviewResult:
    """Result of the manual review gate check."""
    decision: GateDecision
    intent: IntentLabel
    confidence: float
    intent_detail: Optional[str] = None
    user_info_updates: Optional[Dict[str, Any]] = None
    room_choice: Optional[str] = None
    should_lock_room: bool = False
    qna_response: Optional[str] = None


def check_manual_review_gate(
    intent: IntentLabel,
    confidence: float,
    linked_event: Optional[Dict[str, Any]],
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
    unified_detection: Any,
    state_message: Any,
) -> ManualReviewResult:
    """Check if message should be routed to manual review or handled specially.

    This gate checks multiple conditions to determine the correct routing:
    1. Skip if existing event at step > 1 (let step handlers deal with it)
    2. Boost to event_request if awaiting billing
    3. Boost to event_request if gate confirmation detected
    4. Boost to event_request if room choice detected
    5. Boost to event_request if billing fragment detected
    6. Handle standalone Q&A without event
    7. Route to manual review if low confidence

    Args:
        intent: Detected intent
        confidence: Confidence score
        linked_event: Existing event if any
        message_payload: Raw message data
        user_info: Extracted user information (will be updated in place)
        unified_detection: Result from get_unified_detection()
        state_message: The message object from state

    Returns:
        ManualReviewResult with decision and any updates
    """
    body_text = message_payload.get("body") or ""
    fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
    user_info_updates: Dict[str, Any] = {}

    # [SKIP MANUAL REVIEW FOR EXISTING EVENTS]
    skip_manual_review_check = linked_event and linked_event.get("current_step", 1) > 1
    if skip_manual_review_check:
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=intent,
            confidence=confidence,
        )

    # Only enter the gate if NOT event_request or confidence < 0.85
    if is_event_request(intent) and confidence >= 0.85:
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=intent,
            confidence=confidence,
        )

    # Check awaiting billing
    awaiting_billing = linked_event and (linked_event.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    if awaiting_billing:
        if body_text.strip() and _looks_like_billing_fragment(body_text):
            user_info_updates["billing_address"] = body_text.strip()
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=IntentLabel.EVENT_REQUEST,
            confidence=max(confidence, 0.9),
            intent_detail="event_intake_billing_update",
            user_info_updates=user_info_updates,
        )

    # Check gate confirmation
    if _looks_like_gate_confirmation(body_text, linked_event):
        iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year or 2026)
        if iso_date:
            user_info_updates["date"] = iso_date
            user_info_updates["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
        if start_time:
            user_info_updates["start_time"] = start_time
        if end_time:
            user_info_updates["end_time"] = end_time
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=IntentLabel.EVENT_REQUEST,
            confidence=max(confidence, 0.95),
            intent_detail="event_intake_followup",
            user_info_updates=user_info_updates,
        )

    # Check room choice
    room_choice = _detect_room_choice(body_text, linked_event, unified_detection)
    if room_choice:
        user_info_updates["room"] = room_choice
        user_info_updates["_room_choice_detected"] = True
        # Only lock immediately if no room is currently locked
        should_lock = False
        if linked_event:
            locked = linked_event.get("locked_room_id")
            if not locked:
                should_lock = True
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=IntentLabel.EVENT_REQUEST,
            confidence=max(confidence, 0.96),
            intent_detail="event_intake_room_choice",
            user_info_updates=user_info_updates,
            room_choice=room_choice,
            should_lock_room=should_lock,
        )

    # Check billing fragment
    if _looks_like_billing_fragment(body_text):
        user_info_updates["billing_address"] = body_text.strip()
        return ManualReviewResult(
            decision=GateDecision.CONTINUE,
            intent=IntentLabel.EVENT_REQUEST,
            confidence=max(confidence, 0.92),
            intent_detail="event_intake_billing_capture",
            user_info_updates=user_info_updates,
        )

    # Check standalone Q&A without event
    is_qna_intent = intent in (IntentLabel.NON_EVENT, IntentLabel.CAPABILITY_QNA) or "qna" in intent.value.lower()
    if is_qna_intent and not linked_event:
        qna_response = _generate_standalone_qna_response(state_message)
        return ManualReviewResult(
            decision=GateDecision.STANDALONE_QNA,
            intent=intent,
            confidence=confidence,
            qna_response=qna_response,
        )

    # Route to manual review
    return ManualReviewResult(
        decision=GateDecision.MANUAL_REVIEW,
        intent=intent,
        confidence=confidence,
    )


def _generate_standalone_qna_response(state_message: Any) -> str:
    """Generate response for standalone Q&A without event context.

    Args:
        state_message: The message object from state

    Returns:
        Response text to send to client
    """
    message_body = state_message.body or ""
    qna_types = _detect_qna_types(message_body.lower())

    hybrid_response = None
    if qna_types:
        hybrid_response = generate_hybrid_qna_response(
            qna_types=qna_types,
            message_text=message_body,
            event_entry=None,
            db=None,
        )

    if hybrid_response:
        qna_response = hybrid_response
    else:
        # Fallback: ask for event details
        qna_response = (
            "Thank you for your question! To help you best, could you let me know if "
            "you're interested in booking an event with us? If so, please share:\n"
            "- Your preferred date\n"
            "- Expected number of guests\n\n"
            "If you have a general question about our venue or services, "
            "feel free to ask and I'll do my best to help."
        )

    return append_footer(
        qna_response,
        step=1,
        next_step=1,
        thread_state="Awaiting Client",
    )
