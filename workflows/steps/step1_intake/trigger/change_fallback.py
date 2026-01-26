"""Change fallback module for legacy routing logic.

This module handles fallback routing for cases not handled by the main
DAG-based change propagation system:
- Date changes when change_type is None (legacy detection)
- Missing date handling (route to Step 2)
- Requirements hash mismatch (route to Step 3)
- Room preference changes (route to Step 3)

These are safety nets that catch edge cases.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from workflows.steps.step2_date_confirmation.trigger.date_parsing import (
    iso_date_is_past,
    normalize_iso_candidate,
)

logger = logging.getLogger(__name__)


class FallbackAction(Enum):
    """Action to take from fallback check."""
    NONE = "none"  # No fallback needed
    PAST_DATE_TO_STEP2 = "past_date_to_step2"
    DATE_CHANGE_TO_STEP3 = "date_change_to_step3"
    DATE_CHANGE_TO_STEP2 = "date_change_to_step2"
    MISSING_DATE_TO_STEP2 = "missing_date_to_step2"
    REQUIREMENTS_TO_STEP3 = "requirements_to_step3"
    ROOM_TO_STEP3 = "room_to_step3"


@dataclass
class FallbackResult:
    """Result of fallback routing check."""
    action: FallbackAction
    next_step: Optional[int] = None
    set_caller_step: Optional[int] = None
    new_date: Optional[str] = None
    date_confirmed: Optional[bool] = None
    audit_reason: Optional[str] = None


def check_date_fallback(
    new_date: Optional[str],
    event_entry: Dict[str, Any],
    previous_step: int,
    skip_guards: Dict[str, bool],
) -> FallbackResult:
    """Check for date-related fallback routing.

    Handles:
    - Past date detection (route to Step 2)
    - Date change from later steps (route to Step 2 or 3)

    Args:
        new_date: New date from user_info
        event_entry: Current event record
        previous_step: Current step
        skip_guards: Dict with skip flags (in_billing_flow, is_qna, etc.)

    Returns:
        FallbackResult with action to take
    """
    if not new_date:
        return FallbackResult(action=FallbackAction.NONE)

    if new_date == event_entry.get("chosen_date"):
        return FallbackResult(action=FallbackAction.NONE)

    # Check all skip guards
    if skip_guards.get("in_billing_flow"):
        return FallbackResult(action=FallbackAction.NONE)
    if skip_guards.get("is_deposit_date_context"):
        return FallbackResult(action=FallbackAction.NONE)
    if skip_guards.get("site_visit_active"):
        return FallbackResult(action=FallbackAction.NONE)
    if skip_guards.get("site_visit_change"):
        return FallbackResult(action=FallbackAction.NONE)
    if skip_guards.get("is_qna_no_change"):
        return FallbackResult(action=FallbackAction.NONE)

    # Check if date is in the past
    normalized_new_date = normalize_iso_candidate(new_date)
    date_is_past = iso_date_is_past(normalized_new_date) if normalized_new_date else False

    if date_is_past:
        logger.info("[Step1] Date %s is in the past - routing to Step 2", new_date)
        return FallbackResult(
            action=FallbackAction.PAST_DATE_TO_STEP2,
            next_step=2,
            new_date=new_date,
            date_confirmed=False,
            audit_reason="past_date_rejected",
        )

    # Date change routing based on previous step
    if previous_step not in (None, 1, 2) and event_entry.get("caller_step") is None:
        if previous_step <= 1:
            return FallbackResult(
                action=FallbackAction.DATE_CHANGE_TO_STEP3,
                next_step=3,
                set_caller_step=previous_step,
                new_date=new_date,
                date_confirmed=True,
                audit_reason="date_updated_initial",
            )
        else:
            return FallbackResult(
                action=FallbackAction.DATE_CHANGE_TO_STEP2,
                next_step=2,
                set_caller_step=previous_step,
                new_date=new_date,
                date_confirmed=False,
                audit_reason="date_updated",
            )
    elif previous_step <= 1:
        return FallbackResult(
            action=FallbackAction.DATE_CHANGE_TO_STEP3,
            next_step=3,
            new_date=new_date,
            date_confirmed=True,
            audit_reason="date_updated_initial",
        )
    else:
        return FallbackResult(
            action=FallbackAction.DATE_CHANGE_TO_STEP2,
            next_step=2,
            new_date=new_date,
            date_confirmed=False,
            audit_reason="date_updated",
        )


def check_missing_date_fallback(
    new_date: Optional[str],
    event_entry: Dict[str, Any],
    change_type: Any,
    needs_vague_date_confirmation: bool,
    previous_step: int,
) -> FallbackResult:
    """Check for missing date fallback routing.

    If no date is available and no change was detected, route to Step 2.

    Args:
        new_date: Date from user_info
        event_entry: Current event record
        change_type: Detected change type (if any)
        needs_vague_date_confirmation: Whether date is vague
        previous_step: Current step

    Returns:
        FallbackResult with action to take
    """
    # Clear new_date if vague confirmation needed
    if needs_vague_date_confirmation:
        new_date = None

    if not new_date and not event_entry.get("chosen_date") and change_type is None:
        return FallbackResult(
            action=FallbackAction.MISSING_DATE_TO_STEP2,
            next_step=2,
            date_confirmed=False,
            audit_reason="date_missing",
        )

    return FallbackResult(action=FallbackAction.NONE)


def check_requirements_hash_fallback(
    prev_req_hash: Optional[str],
    new_req_hash: Optional[str],
    event_entry: Dict[str, Any],
    previous_step: int,
    change_type: Any,
    detoured_to_step2: bool,
    is_qna_no_change: bool,
) -> FallbackResult:
    """Check for requirements hash mismatch fallback routing.

    If requirements changed but DAG didn't detect it, route to Step 3.

    Args:
        prev_req_hash: Previous requirements hash
        new_req_hash: New requirements hash
        event_entry: Current event record
        previous_step: Current step
        change_type: Detected change type
        detoured_to_step2: Whether already routed to Step 2
        is_qna_no_change: Whether this is a Q&A (should skip)

    Returns:
        FallbackResult with action to take
    """
    # Skip if conditions not met
    if prev_req_hash is None:
        return FallbackResult(action=FallbackAction.NONE)
    if prev_req_hash == new_req_hash:
        return FallbackResult(action=FallbackAction.NONE)
    if detoured_to_step2:
        return FallbackResult(action=FallbackAction.NONE)
    if change_type is not None:
        return FallbackResult(action=FallbackAction.NONE)

    # Q&A guard
    if is_qna_no_change:
        logger.debug(
            "[Step1][HASH_QNA_GUARD] Skipping requirements hash routing - Q&A question detected: "
            "prev_hash=%s, new_hash=%s",
            prev_req_hash[:8] if prev_req_hash else None,
            new_req_hash[:8] if new_req_hash else None
        )
        return FallbackResult(action=FallbackAction.NONE)

    target_step = 3
    if previous_step != target_step and event_entry.get("caller_step") is None:
        return FallbackResult(
            action=FallbackAction.REQUIREMENTS_TO_STEP3,
            next_step=3,
            set_caller_step=previous_step,
            audit_reason="requirements_updated",
        )

    return FallbackResult(action=FallbackAction.NONE)


def check_room_preference_fallback(
    new_preferred_room: Optional[str],
    event_entry: Dict[str, Any],
    previous_step: int,
    change_type: Any,
    detoured_to_step2: bool,
    is_qna_no_change: bool,
    in_billing_flow: bool,
) -> FallbackResult:
    """Check for room preference change fallback routing.

    If room preference changed but DAG didn't detect it, route to Step 3.

    Args:
        new_preferred_room: New preferred room
        event_entry: Current event record
        previous_step: Current step
        change_type: Detected change type
        detoured_to_step2: Whether already routed to Step 2
        is_qna_no_change: Whether this is a Q&A (should skip)
        in_billing_flow: Whether in billing flow

    Returns:
        FallbackResult with action to take
    """
    if not new_preferred_room:
        return FallbackResult(action=FallbackAction.NONE)
    if new_preferred_room == event_entry.get("locked_room_id"):
        return FallbackResult(action=FallbackAction.NONE)
    if change_type is not None:
        return FallbackResult(action=FallbackAction.NONE)
    if detoured_to_step2:
        return FallbackResult(action=FallbackAction.NONE)
    if in_billing_flow:
        return FallbackResult(action=FallbackAction.NONE)

    # Q&A guard
    if is_qna_no_change:
        logger.debug(
            "[Step1][ROOM_QNA_GUARD] Skipping room routing - Q&A question detected: room=%s",
            new_preferred_room
        )
        return FallbackResult(action=FallbackAction.NONE)

    prev_step_for_room = event_entry.get("current_step") or previous_step
    if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
        return FallbackResult(
            action=FallbackAction.ROOM_TO_STEP3,
            next_step=3,
            set_caller_step=prev_step_for_room,
            audit_reason="room_preference_updated",
        )

    return FallbackResult(action=FallbackAction.NONE)
