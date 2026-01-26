"""Smart shortcut module for room availability verification.

This module handles the "smart shortcut" flow where a new event request
contains room + date + participants upfront. Instead of going through
the normal Step 1 -> 2 -> 3 -> 4 flow, we verify room availability inline
and jump directly to Step 4 (offer generation).

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.room_eval import evaluate_rooms
from workflows.io.database import append_audit_entry, update_event_metadata
from workflows.steps.step2_date_confirmation.trigger.date_parsing import (
    iso_date_is_past,
    normalize_iso_candidate,
)

logger = logging.getLogger(__name__)


@dataclass
class PastDateResult:
    """Result of past date detection."""
    is_past: bool
    original_date: Optional[str] = None


@dataclass
class ShortcutEligibility:
    """Eligibility check for smart shortcut."""
    is_eligible: bool
    preferred_room: Optional[str] = None
    event_date: Optional[str] = None
    participants: Optional[int] = None
    reason: Optional[str] = None  # Reason if not eligible


@dataclass
class SmartShortcutResult:
    """Result of smart shortcut evaluation."""
    success: bool
    room_name: Optional[str] = None
    room_status: Optional[str] = None
    missing_products: Optional[List[str]] = None
    reason: Optional[str] = None  # Reason if not successful

    def __post_init__(self) -> None:
        if self.missing_products is None:
            self.missing_products = []


def check_past_date(
    event_date: Optional[str],
    date_confirmed: bool,
) -> PastDateResult:
    """Check if the extracted date is in the past.

    Args:
        event_date: Date from user_info
        date_confirmed: Whether date is already confirmed

    Returns:
        PastDateResult indicating if date is past
    """
    if not event_date or date_confirmed:
        return PastDateResult(is_past=False)

    normalized_date = normalize_iso_candidate(event_date)
    if normalized_date and iso_date_is_past(normalized_date):
        logger.info("[Step1][PAST_DATE] Date %s is in the past", event_date)
        return PastDateResult(is_past=True, original_date=event_date)

    return PastDateResult(is_past=False)


def check_shortcut_eligibility(
    event_entry: Dict[str, Any],
    requirements: Dict[str, Any],
    user_info: Dict[str, Any],
    past_date_detected: bool,
    needs_vague_date_confirmation: bool,
) -> ShortcutEligibility:
    """Check if event is eligible for smart shortcut.

    Eligibility requirements:
    1. No existing room lock (new event)
    2. Date not yet confirmed
    3. Has preferred room, event date, and participants
    4. Date is not in the past
    5. Date is not vague (needs confirmation)

    Args:
        event_entry: Current event record
        requirements: Built requirements dict
        user_info: Extracted user information
        past_date_detected: Whether date was detected as past
        needs_vague_date_confirmation: Whether date is vague

    Returns:
        ShortcutEligibility with eligibility status and fields
    """
    preferred_room = requirements.get("preferred_room") or user_info.get("room")
    event_date = user_info.get("event_date") or user_info.get("date")
    participants = requirements.get("participants") or requirements.get("number_of_participants")

    # Check for existing room lock or confirmed date
    if event_entry.get("locked_room_id"):
        return ShortcutEligibility(
            is_eligible=False,
            reason="existing_room_lock",
        )

    if event_entry.get("date_confirmed"):
        return ShortcutEligibility(
            is_eligible=False,
            reason="date_already_confirmed",
        )

    # Check for past date
    if past_date_detected:
        return ShortcutEligibility(
            is_eligible=False,
            preferred_room=preferred_room,
            event_date=None,  # Clear for shortcut
            participants=participants,
            reason="past_date",
        )

    # Check for vague date
    if needs_vague_date_confirmation:
        return ShortcutEligibility(
            is_eligible=False,
            preferred_room=preferred_room,
            event_date=event_date,
            participants=participants,
            reason="vague_date",
        )

    # Check all required fields
    if not (preferred_room and event_date and participants):
        missing = []
        if not preferred_room:
            missing.append("room")
        if not event_date:
            missing.append("date")
        if not participants:
            missing.append("participants")
        return ShortcutEligibility(
            is_eligible=False,
            preferred_room=preferred_room,
            event_date=event_date,
            participants=participants,
            reason=f"missing_fields:{','.join(missing)}",
        )

    return ShortcutEligibility(
        is_eligible=True,
        preferred_room=preferred_room,
        event_date=event_date,
        participants=participants,
    )


def evaluate_smart_shortcut(
    event_entry: Dict[str, Any],
    db: Dict[str, Any],
    eligibility: ShortcutEligibility,
    user_info: Dict[str, Any],
) -> SmartShortcutResult:
    """Evaluate room availability for smart shortcut.

    Sets up the event_entry with requested_window and evaluates room
    availability. If the room is available, returns success.

    Args:
        event_entry: Current event record (will be mutated with requested_window)
        db: Database dict for room evaluation
        eligibility: Pre-checked eligibility
        user_info: Extracted user information (for start/end times)

    Returns:
        SmartShortcutResult with evaluation results
    """
    if not eligibility.is_eligible:
        return SmartShortcutResult(success=False, reason=eligibility.reason)

    preferred_room = eligibility.preferred_room
    event_date = eligibility.event_date

    logger.debug(
        "[Step1][SMART_SHORTCUT] Checking inline availability: room=%s, date=%s, participants=%s",
        preferred_room, event_date, eligibility.participants
    )

    # Set up event_entry with requested_window for evaluate_rooms
    start_time = user_info.get("start_time") or "09:00"
    end_time = user_info.get("end_time") or "18:00"
    event_entry["requested_window"] = {
        "date_iso": event_date,
        "start": start_time,
        "end": end_time,
    }
    event_entry["chosen_date"] = event_date

    # Evaluate room availability
    try:
        evaluations = evaluate_rooms(event_entry, db=db)
        target_eval = next(
            (e for e in evaluations if e.record.name.lower() == str(preferred_room).lower()),
            None
        )

        if target_eval and target_eval.status in ("Available", "Option"):
            logger.info(
                "[Step1][SMART_SHORTCUT] Room %s is %s - eligible for jump to Step 4",
                preferred_room, target_eval.status
            )
            missing_products: List[str] = []
            if target_eval.missing_products:
                missing_products = [str(p.get("name") or "") for p in target_eval.missing_products if p.get("name")]

            return SmartShortcutResult(
                success=True,
                room_name=target_eval.record.name,
                room_status=target_eval.status,
                missing_products=missing_products,
            )
        else:
            status_msg = target_eval.status if target_eval else "not found"
            logger.debug(
                "[Step1][SMART_SHORTCUT] Room %s not available (status=%s) - proceeding normally",
                preferred_room, status_msg
            )
            return SmartShortcutResult(
                success=False,
                reason=f"room_unavailable:{status_msg}",
            )

    except Exception as ex:
        logger.warning("[Step1][SMART_SHORTCUT] Room evaluation failed: %s - proceeding normally", ex)
        return SmartShortcutResult(
            success=False,
            reason=f"evaluation_error:{ex}",
        )


def apply_smart_shortcut(
    event_entry: Dict[str, Any],
    shortcut_result: SmartShortcutResult,
    event_date: str,
    new_req_hash: Optional[str],
    participants: Optional[int],
) -> str:
    """Apply smart shortcut result to event_entry.

    This updates the event_entry with all the metadata needed to jump to Step 4.

    Args:
        event_entry: Current event record (will be mutated)
        shortcut_result: Result from evaluate_smart_shortcut
        event_date: The event date
        new_req_hash: New requirements hash
        participants: Number of participants

    Returns:
        The confirmation intro text for room_confirmation_prefix
    """
    if not shortcut_result.success:
        raise ValueError(f"Cannot apply shortcut: {shortcut_result.reason}")

    room_name = shortcut_result.room_name
    room_status = shortcut_result.room_status

    update_event_metadata(
        event_entry,
        chosen_date=event_date,
        date_confirmed=True,
        locked_room_id=room_name,
        room_status=room_status,
        room_eval_hash=new_req_hash,
        current_step=4,
        thread_state="Awaiting Client",
        caller_step=None,
    )
    event_entry.setdefault("event_data", {})["Event Date"] = event_date
    event_entry.setdefault("event_data", {})["Preferred Room"] = room_name
    append_audit_entry(event_entry, 1, 4, "smart_shortcut_room_verified")

    # Store pending decision for Step 4 to use
    event_entry["room_pending_decision"] = {
        "selected_room": room_name,
        "selected_status": room_status,
        "missing_products": shortcut_result.missing_products,
    }

    # Build confirmation intro
    confirmation_intro = (
        f"Great choice! {room_name} on {event_date or 'your date'} is confirmed"
    )
    if participants:
        confirmation_intro += f" for your event with {participants} guests."
    else:
        confirmation_intro += "."
    event_entry["room_confirmation_prefix"] = confirmation_intro + "\n\n"
    logger.info("[Step1][SMART_SHORTCUT] Set room_confirmation_prefix for Step 4")

    return confirmation_intro
