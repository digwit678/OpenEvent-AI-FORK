"""Early detection module for intake signals.

This module contains functions for detecting early workflow signals that
influence routing and confidence scoring:
- Confirmation detection (date/time from gate confirmations)
- Offer acceptance detection
- Hybrid Q&A detection
- Room choice detection
- Menu choice detection
- Product update detection

These functions are read-only and return results - they do NOT mutate state.
The main handler is responsible for applying the results to state.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from domain import IntentLabel
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from .confirmation_parsing import (
    extract_confirmation_details as _extract_confirmation_details,
    looks_like_gate_confirmation as _looks_like_gate_confirmation,
)
from .gate_confirmation import looks_like_offer_acceptance as _looks_like_offer_acceptance
from .room_detection import detect_room_choice as _detect_room_choice
from .product_detection import detect_menu_choice as _detect_menu_choice
from .entity_extraction import participants_from_event as _participants_from_event

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationResult:
    """Result of confirmation detection."""
    detected: bool
    iso_date: Optional[str] = None
    event_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


@dataclass
class AcceptanceResult:
    """Result of offer acceptance detection."""
    detected: bool
    target_step: Optional[int] = None


@dataclass
class RoomChoiceResult:
    """Result of room choice detection."""
    room_name: Optional[str] = None
    should_bump_confidence: bool = False


@dataclass
class MenuChoiceResult:
    """Result of menu choice detection."""
    menu_name: Optional[str] = None
    product_payload: Optional[Dict[str, Any]] = None


@dataclass
class QnaSignalResult:
    """Result of Q&A signal detection."""
    has_qna_types: bool = False
    is_question: bool = False
    should_set_general_qna: bool = False


def detect_confirmation(
    body_text: str,
    linked_event: Optional[Dict[str, Any]],
    user_info: Dict[str, Any],
    fallback_year: Optional[int] = None,
) -> ConfirmationResult:
    """Detect if message contains gate confirmation with date/time.

    Args:
        body_text: Normalized message body
        linked_event: Existing event if any
        user_info: Extracted user information
        fallback_year: Year to use for date parsing if none specified

    Returns:
        ConfirmationResult with detected fields
    """
    if not (linked_event
            and not user_info.get("date")
            and not user_info.get("event_date")
            and _looks_like_gate_confirmation(body_text, linked_event)):
        return ConfirmationResult(detected=False)

    iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year or 2026)
    if not iso_date:
        return ConfirmationResult(detected=False)

    return ConfirmationResult(
        detected=True,
        iso_date=iso_date,
        event_date=format_iso_date_to_ddmmyyyy(iso_date),
        start_time=start_time,
        end_time=end_time,
    )


def detect_offer_acceptance(
    body_text: str,
    linked_event: Optional[Dict[str, Any]],
) -> AcceptanceResult:
    """Detect if message is an offer acceptance.

    Args:
        body_text: Normalized message body
        linked_event: Existing event if any

    Returns:
        AcceptanceResult with target step if detected
    """
    if not linked_event:
        return AcceptanceResult(detected=False)

    if not _looks_like_offer_acceptance(body_text):
        return AcceptanceResult(detected=False)

    target_step = max(linked_event.get("current_step") or 0, 5)
    return AcceptanceResult(detected=True, target_step=target_step)


def detect_qna_signals(unified_detection: Any) -> QnaSignalResult:
    """Detect Q&A signals from unified detection.

    Args:
        unified_detection: Result from get_unified_detection()

    Returns:
        QnaSignalResult with Q&A detection flags
    """
    has_qna_types = bool(getattr(unified_detection, "qna_types", None) if unified_detection else False)
    is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)

    return QnaSignalResult(
        has_qna_types=has_qna_types,
        is_question=is_question,
        should_set_general_qna=has_qna_types and is_question,
    )


def detect_early_room_choice(
    body_text: str,
    linked_event: Optional[Dict[str, Any]],
    unified_detection: Any,
) -> RoomChoiceResult:
    """Detect early room choice from message.

    Args:
        body_text: Normalized message body
        linked_event: Existing event if any
        unified_detection: Result from get_unified_detection()

    Returns:
        RoomChoiceResult with room name if detected
    """
    room_choice = _detect_room_choice(body_text, linked_event, unified_detection)
    if room_choice:
        logger.info("[Step1] early_room_choice=%s (linked_event.current_step=%s)",
                    room_choice, linked_event.get("current_step") if linked_event else None)
        return RoomChoiceResult(room_name=room_choice, should_bump_confidence=True)
    return RoomChoiceResult()


def detect_early_menu_choice(
    body_text: str,
    linked_event: Optional[Dict[str, Any]],
    user_info: Dict[str, Any],
) -> MenuChoiceResult:
    """Detect menu choice from message and build product payload.

    Args:
        body_text: Normalized message body
        linked_event: Existing event if any
        user_info: Extracted user information

    Returns:
        MenuChoiceResult with menu name and product payload if detected
    """
    menu_choice = _detect_menu_choice(body_text)
    if not menu_choice:
        return MenuChoiceResult()

    participants = _participants_from_event(linked_event) or user_info.get("participants")
    try:
        participants = int(participants) if participants is not None else None
    except (TypeError, ValueError):
        participants = None

    product_payload = None
    if menu_choice.get("price"):
        product_payload = {
            "name": menu_choice["name"],
            "quantity": 1 if menu_choice.get("unit") == "per_event" else (participants or 1),
            "unit_price": menu_choice["price"],
            "unit": menu_choice.get("unit") or "per_event",
            "category": "Catering",
            "wish": "menu",
        }

    return MenuChoiceResult(
        menu_name=menu_choice["name"],
        product_payload=product_payload,
    )


def should_boost_confidence(
    intent: IntentLabel,
    confidence: float,
    user_info: Dict[str, Any],
) -> Tuple[bool, float]:
    """Check if confidence should be boosted for clear event requests.

    When LLM detects event_request intent AND we have both date and participants,
    this is unambiguously an event inquiry - boost confidence to avoid false manual_review.

    Args:
        intent: Detected intent
        confidence: Current confidence score
        user_info: Extracted user information

    Returns:
        Tuple of (should_boost, new_confidence)
    """
    from ..condition.checks import is_event_request

    if not is_event_request(intent) or confidence >= 0.85:
        return False, confidence

    has_date = bool(user_info.get("date") or user_info.get("event_date"))
    has_participants = bool(user_info.get("participants"))

    if has_date and has_participants:
        logger.info(
            "[Step1] Boosting confidence %.2f -> 0.90 for clear event request "
            "(has date=%s, participants=%s)",
            confidence, user_info.get("date"), user_info.get("participants")
        )
        return True, 0.90

    return False, confidence
