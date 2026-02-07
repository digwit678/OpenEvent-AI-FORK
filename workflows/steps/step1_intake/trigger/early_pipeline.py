"""Early detection pipeline for Step 1 intake.

Chains together confirmation, acceptance, Q&A signal, time validation,
room choice, menu choice, and product-update detections.  Returns an
``EarlyPipelineResult`` dataclass — the caller applies detected values
to ``state`` / ``user_info`` / ``event_entry``.  This module never
mutates workflow state directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from domain import IntentLabel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class EarlyPipelineResult:
    """Aggregate output of the early-detection pipeline."""

    # Confirmation detection
    confirmation_detected: bool = False
    confirmation_date_iso: Optional[str] = None
    confirmation_event_date: Optional[str] = None
    confirmation_start_time: Optional[str] = None
    confirmation_end_time: Optional[str] = None

    # Acceptance detection
    acceptance_detected: bool = False
    acceptance_target_step: Optional[int] = None

    # Q&A signals
    should_set_general_qna: bool = False

    # Time validation
    time_valid: bool = True
    time_warning: Optional[str] = None
    time_warning_issue: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None

    # Room choice
    room_name: Optional[str] = None
    room_should_bump_confidence: bool = False

    # Menu choice
    menu_name: Optional[str] = None
    menu_product_payload: Optional[Dict[str, Any]] = None

    # Product update
    product_update_detected: bool = False

    # Overridden intent / confidence (when acceptance or room bumps them)
    override_intent: Optional[IntentLabel] = None
    override_confidence: Optional[float] = None
    override_intent_detail: Optional[str] = None
    extras_updates: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline function
# ---------------------------------------------------------------------------
def run_early_detection_pipeline(
    *,
    body_text: str,
    linked_event: Optional[Dict[str, Any]],
    user_info: Dict[str, Any],
    fallback_year: Optional[int],
    unified_detection: Any,
    message_payload: Dict[str, Any],
    current_intent: IntentLabel,
    current_confidence: float,
    current_intent_detail: Optional[str],
) -> EarlyPipelineResult:
    """Run all early detections and return an aggregate result.

    This is a *pure-ish* function: it reads from its arguments and returns
    a result dataclass.  It does NOT mutate ``state``, ``user_info``, or
    ``linked_event``.
    """
    from .early_detection import (
        detect_confirmation,
        detect_offer_acceptance,
        detect_qna_signals,
        detect_early_room_choice,
        detect_early_menu_choice,
    )
    from .product_detection import detect_product_update_request
    from workflows.common.time_validation import validate_event_times
    from ..condition.checks import is_event_request

    result = EarlyPipelineResult()
    intent = current_intent
    confidence = current_confidence
    intent_detail = current_intent_detail

    # --- confirmation ---
    confirmation_result = detect_confirmation(body_text, linked_event, user_info, fallback_year)
    result.confirmation_detected = confirmation_result.detected
    if confirmation_result.detected:
        result.confirmation_date_iso = confirmation_result.iso_date
        result.confirmation_event_date = confirmation_result.event_date
        result.confirmation_start_time = confirmation_result.start_time
        result.confirmation_end_time = confirmation_result.end_time

    # --- offer acceptance ---
    acceptance_result = detect_offer_acceptance(body_text, linked_event)
    if acceptance_result.detected and linked_event:
        result.acceptance_detected = True
        result.acceptance_target_step = acceptance_result.target_step
        intent = IntentLabel.EVENT_REQUEST
        confidence = max(confidence, 0.99)
        if intent_detail in (None, "intake"):
            intent_detail = "event_intake_negotiation_accept"
        result.extras_updates["persist"] = True

    # --- Q&A signals ---
    qna_signals = detect_qna_signals(unified_detection)
    result.should_set_general_qna = qna_signals.should_set_general_qna

    # --- time validation ---
    time_validation = validate_event_times(
        start_time=unified_detection.start_time if unified_detection else None,
        end_time=unified_detection.end_time if unified_detection else None,
        is_site_visit=False,
    )
    if not time_validation.is_valid:
        logger.info(
            "[Step1][TIME_VALIDATION] Times outside hours: %s (start=%s, end=%s)",
            time_validation.issue, time_validation.start_time, time_validation.end_time,
        )
        result.time_valid = False
        result.time_warning = time_validation.friendly_message
        result.time_warning_issue = time_validation.issue
        result.time_start = time_validation.start_time
        result.time_end = time_validation.end_time

    # --- room choice ---
    room_result = detect_early_room_choice(body_text, linked_event, unified_detection)
    if room_result.room_name:
        result.room_name = room_result.room_name
        result.room_should_bump_confidence = room_result.should_bump_confidence
        if room_result.should_bump_confidence:
            confidence = 1.0
            intent = IntentLabel.EVENT_REQUEST

    # --- menu choice ---
    menu_result = detect_early_menu_choice(body_text, linked_event, user_info)
    if menu_result.menu_name:
        result.menu_name = menu_result.menu_name
        result.menu_product_payload = menu_result.product_payload

    # --- product update ---
    product_update_detected = detect_product_update_request(message_payload, user_info, linked_event)
    if product_update_detected:
        result.product_update_detected = True
        if not is_event_request(intent):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.9)
            intent_detail = "event_intake_product_update"
        elif intent_detail in (None, "intake", "event_intake"):
            intent_detail = "event_intake_product_update"

    # --- set overrides only if they changed ---
    if intent != current_intent or confidence != current_confidence:
        result.override_intent = intent
        result.override_confidence = confidence
    if intent_detail != current_intent_detail:
        result.override_intent_detail = intent_detail

    return result
