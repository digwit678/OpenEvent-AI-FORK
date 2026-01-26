"""Room confirmation module for room choice capture.

This module handles the logic for capturing a room choice and transitioning
to Step 4 (offer generation). It handles:
- Room change detection (existing lock vs new selection)
- Missing products bypass (for arrangement flows)
- Room confirmation prefix generation
- Draft message generation for room confirmed response

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.common.catalog import list_room_features
from workflows.io.database import append_audit_entry, update_event_metadata
from detection.intent.classifier import _detect_qna_types
from workflows.qna.router import generate_hybrid_qna_response

logger = logging.getLogger(__name__)


class RoomConfirmDecision(Enum):
    """Decision for room confirmation."""
    SKIP = "skip"  # Different room already locked - let change detection handle
    DEFER_ARRANGEMENT = "defer_arrangement"  # Missing products - defer to Step 3
    CONFIRM_AND_ADVANCE = "confirm_and_advance"  # Lock room and advance to Step 4


@dataclass
class RoomConfirmResult:
    """Result of room confirmation check."""
    decision: RoomConfirmDecision
    room_name: Optional[str] = None
    room_status: Optional[str] = None
    chosen_date: Optional[str] = None
    missing_products: Optional[List[str]] = None
    confirmation_intro: Optional[str] = None
    draft_message: Optional[Dict[str, Any]] = None
    hybrid_qna_response: Optional[str] = None


def check_room_confirmation(
    room_choice_selected: Optional[str],
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
    state_extras: Dict[str, Any],
    message_body: str,
    db: Dict[str, Any],
) -> RoomConfirmResult:
    """Check how to handle a selected room choice.

    This function determines whether to:
    1. Skip (different room already locked - let change detection handle)
    2. Defer to Step 3 for arrangement (missing products)
    3. Confirm and advance to Step 4

    Args:
        room_choice_selected: The room that was selected
        event_entry: Current event record
        user_info: Extracted user information
        state_extras: state.extras dict for Q&A detection
        message_body: Message body for hybrid Q&A
        db: Database dict

    Returns:
        RoomConfirmResult with decision and any generated content
    """
    if not room_choice_selected:
        return RoomConfirmResult(decision=RoomConfirmDecision.SKIP)

    existing_lock = event_entry.get("locked_room_id")

    # Check if different room is already locked
    if existing_lock and existing_lock != room_choice_selected:
        logger.debug("[Step1] Room change detected: %s -> %s, skipping room_choice_captured",
                    existing_lock, room_choice_selected)
        return RoomConfirmResult(decision=RoomConfirmDecision.SKIP)

    # Check pending decision info
    pending_info = event_entry.get("room_pending_decision") or {}
    selected_status = None
    if isinstance(pending_info, dict) and pending_info.get("selected_room") == room_choice_selected:
        selected_status = pending_info.get("selected_status")
    status_value = selected_status or "Available"

    # Get chosen date
    chosen_date = (
        event_entry.get("chosen_date")
        or user_info.get("event_date")
        or user_info.get("date")
    )

    # Check for missing products that need arrangement
    missing_products_for_room = (pending_info or {}).get("missing_products", [])
    if missing_products_for_room:
        logger.debug("[Step1] Room has missing products %s - letting Step 3 handle arrangement",
                    missing_products_for_room)
        return RoomConfirmResult(
            decision=RoomConfirmDecision.DEFER_ARRANGEMENT,
            room_name=room_choice_selected,
            missing_products=missing_products_for_room,
        )

    # Generate confirmation intro
    participants_count = user_info.get("participants")
    chosen_date_display = (
        event_entry.get("chosen_date")
        or event_entry.get("event_data", {}).get("Event Date")
        or "your date"
    )
    confirmation_intro = f"Great choice! {room_choice_selected} on {chosen_date_display} is confirmed"
    if participants_count:
        confirmation_intro += f" for your event with {participants_count} guests."
    else:
        confirmation_intro += "."

    # Generate hybrid Q&A response if needed
    hybrid_qna_response = None
    if state_extras.get("general_qna_detected"):
        hybrid_qna_response = _generate_hybrid_qna(
            state_extras=state_extras,
            message_body=message_body,
            event_entry=event_entry,
            db=db,
        )

    # Generate draft message
    draft_message = _generate_room_confirmed_draft(
        room_name=room_choice_selected,
        chosen_date=chosen_date or "",
        event_entry=event_entry,
    )

    return RoomConfirmResult(
        decision=RoomConfirmDecision.CONFIRM_AND_ADVANCE,
        room_name=room_choice_selected,
        room_status=status_value,
        chosen_date=chosen_date,
        confirmation_intro=confirmation_intro + "\n\n",
        draft_message=draft_message,
        hybrid_qna_response=hybrid_qna_response,
    )


def apply_room_confirmation(
    event_entry: Dict[str, Any],
    result: RoomConfirmResult,
    current_step: int,
) -> None:
    """Apply room confirmation result to event_entry.

    This updates the event metadata for room lock and step transition.

    Args:
        event_entry: Current event record (will be mutated)
        result: Result from check_room_confirmation
        current_step: Current step number for audit entry
    """
    if result.decision != RoomConfirmDecision.CONFIRM_AND_ADVANCE:
        raise ValueError(f"Cannot apply: decision is {result.decision}")

    update_event_metadata(
        event_entry,
        locked_room_id=result.room_name,
        room_status=result.room_status,
        room_eval_hash=event_entry.get("requirements_hash"),
        caller_step=None,
        current_step=4,
        thread_state="Awaiting Client",
    )
    event_entry.setdefault("event_data", {})["Preferred Room"] = result.room_name
    append_audit_entry(event_entry, current_step or 1, 4, "room_choice_captured")

    # Store room confirmation prefix for Step 4
    event_entry["room_confirmation_prefix"] = result.confirmation_intro

    logger.info("[Step1] Set room_confirmation_prefix for Step 4")


def _generate_hybrid_qna(
    state_extras: Dict[str, Any],
    message_body: str,
    event_entry: Dict[str, Any],
    db: Dict[str, Any],
) -> Optional[str]:
    """Generate hybrid Q&A response if general Q&A was detected.

    Args:
        state_extras: state.extras dict
        message_body: Message body for Q&A
        event_entry: Current event record
        db: Database dict

    Returns:
        Q&A response text if generated, None otherwise
    """
    unified_detection = state_extras.get("unified_detection") or {}
    qna_types = unified_detection.get("qna_types") or []
    if not qna_types:
        qna_types = _detect_qna_types(message_body.lower())
        if not qna_types:
            qna_types = ["general"]

    logger.debug("[HYBRID Step1] qna_types=%s", qna_types)

    if qna_types:
        hybrid_qna_response = generate_hybrid_qna_response(
            qna_types=qna_types,
            message_text=message_body,
            event_entry=event_entry,
            db=db,
        )
        if hybrid_qna_response:
            logger.debug("[Step1] Generated hybrid Q&A response for room shortcut: %s chars",
                        len(hybrid_qna_response))
            return hybrid_qna_response

    return None


def _generate_room_confirmed_draft(
    room_name: str,
    chosen_date: str,
    event_entry: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate draft message for room confirmation.

    Args:
        room_name: Name of the confirmed room
        chosen_date: The chosen date (ISO format or display format)
        event_entry: Current event record

    Returns:
        Draft message dict
    """
    display_date = format_iso_date_to_ddmmyyyy(chosen_date) if chosen_date else "your date"
    participants = (event_entry.get("requirements") or {}).get("participants", "")
    participants_str = f" for {participants} guests" if participants else ""

    # Get room features for the selected room
    room_features = list_room_features(room_name)
    features_str = ""
    if room_features:
        features_str = f"\n\nFeatures: {', '.join(room_features[:6])}"

    confirmation_body = (
        f"Great choice! {room_name} on {display_date} is confirmed{participants_str}."
        f"{features_str}"
        f"\n\nI'll prepare the offer for you now."
    )

    return {
        "body_markdown": confirmation_body,
        "step": 4,
        "topic": "room_confirmed",
        "headers": ["Room Confirmed"],
        "thread_state": "Awaiting Client",
        "requires_approval": False,
    }
