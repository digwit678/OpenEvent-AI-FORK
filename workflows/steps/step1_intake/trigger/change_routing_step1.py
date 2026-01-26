"""Step1-specific change detection and routing module.

This module wraps the centralized change_propagation system with Step1-specific
guards and context checks:
- Billing flow bypass (billing addresses shouldn't trigger changes)
- Deposit date context (payment dates aren't event dates)
- Site visit guards (site visit dates aren't event dates)
- Q&A guards (questions about dates aren't date changes)
- Vague date handling

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from workflows.change_propagation import (
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.site_visit_state import (
    is_site_visit_active,
    is_site_visit_scheduled,
    is_site_visit_change_request,
)

logger = logging.getLogger(__name__)


# Pattern to detect deposit/payment date mentions
_DEPOSIT_DATE_PATTERN = re.compile(
    r'\b(paid|payment|transferred|deposit)\b.*\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|'
    r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b.*\b(paid|payment|transferred|deposit)\b',
    re.IGNORECASE
)


@dataclass
class ChangeContext:
    """Context information for change detection."""
    in_billing_flow: bool = False
    is_deposit_date_context: bool = False
    site_visit_active: bool = False
    site_visit_scheduled: bool = False
    is_sv_change_request: bool = False
    has_qna_question: bool = False
    llm_is_question: bool = False
    llm_general_qna: bool = False
    llm_change_request: bool = False
    date_already_confirmed: bool = False


@dataclass
class ChangeDetectionResult:
    """Result of change detection with Step1 guards applied."""
    change_type: Optional[Any] = None  # ChangeType enum
    suppressed: bool = False
    suppression_reason: Optional[str] = None
    is_qna_no_change: bool = False


@dataclass
class ChangeRoutingDecision:
    """Decision for how to route based on detected change."""
    next_step: int
    caller_step: Optional[int] = None
    should_clear_room_lock: bool = False
    should_clear_date_confirmed: bool = False
    should_clear_offer_hash: bool = False
    should_clear_billing_flow: bool = False
    should_set_change_detour: bool = False


def build_change_context(
    event_entry: Dict[str, Any],
    message_text: str,
    unified_detection: Any,
    state_extras: Dict[str, Any],
) -> ChangeContext:
    """Build context information needed for change detection guards.

    Args:
        event_entry: Current event record
        message_text: Message body text (NOT subject)
        unified_detection: Result from get_unified_detection()
        state_extras: state.extras dict

    Returns:
        ChangeContext with all guard flags
    """
    # Check billing flow
    in_billing_flow = (
        event_entry.get("offer_accepted")
        and (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )

    # Check deposit date context
    is_deposit_date_context = bool(message_text and _DEPOSIT_DATE_PATTERN.search(message_text))

    # Check site visit status
    site_visit_active = is_site_visit_active(event_entry)
    site_visit_scheduled = is_site_visit_scheduled(event_entry)
    is_sv_change_request = is_site_visit_change_request(message_text or "")

    # Check Q&A signals
    has_qna_question = state_extras.get("general_qna_detected", False)
    llm_is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    llm_general_qna = bool(
        getattr(unified_detection, "intent", "") in ("general_qna", "non_event") if unified_detection else False
    )

    # Check change request signal
    llm_change_request = bool(getattr(unified_detection, "is_change_request", False) if unified_detection else False)

    # Check date confirmation
    date_already_confirmed = event_entry.get("date_confirmed", False)

    return ChangeContext(
        in_billing_flow=bool(in_billing_flow),
        is_deposit_date_context=is_deposit_date_context,
        site_visit_active=site_visit_active,
        site_visit_scheduled=site_visit_scheduled,
        is_sv_change_request=is_sv_change_request,
        has_qna_question=bool(has_qna_question),
        llm_is_question=llm_is_question,
        llm_general_qna=llm_general_qna,
        llm_change_request=llm_change_request,
        date_already_confirmed=bool(date_already_confirmed),
    )


def detect_change_with_guards(
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
    message_text: str,
    unified_detection: Any,
    context: ChangeContext,
) -> ChangeDetectionResult:
    """Detect changes with Step1-specific guards applied.

    Guards in order:
    1. Deposit date context - skip all change detection
    2. Billing flow without change signal - skip all change detection
    3. Site visit active - suppress DATE changes only
    4. Site visit change request - suppress DATE changes only

    Args:
        event_entry: Current event record
        user_info: Extracted user information
        message_text: Message body text
        unified_detection: Result from get_unified_detection()
        context: Pre-built change context

    Returns:
        ChangeDetectionResult with detected change and any suppression
    """
    # Guard: Deposit date context - skip all detection
    if context.is_deposit_date_context:
        return ChangeDetectionResult(
            suppressed=True,
            suppression_reason="deposit_date_context",
        )

    # Guard: Billing flow without explicit change signal
    if context.in_billing_flow:
        # Check for change signal
        from workflows.steps.step5_negotiation.trigger.step5_handler import _looks_like_date_change
        message_looks_like_date_change = False
        if unified_detection is None:
            message_looks_like_date_change = _looks_like_date_change(message_text)
        change_request_signal = context.llm_change_request or message_looks_like_date_change

        if not change_request_signal:
            return ChangeDetectionResult(
                suppressed=True,
                suppression_reason="billing_flow_no_change_signal",
            )

    # Run enhanced detection
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

    # Guard: Site visit active - suppress DATE changes
    if context.site_visit_active and change_type and change_type.value == "date":
        logger.info("[Step1][SV_GUARD] Site visit active - suppressing date change detection")
        return ChangeDetectionResult(
            suppressed=True,
            suppression_reason="site_visit_active",
        )

    # Guard: Site visit change request - suppress DATE changes
    if context.site_visit_scheduled and context.is_sv_change_request and change_type and change_type.value == "date":
        logger.info("[Step1][SV_GUARD] Site visit change request detected - suppressing event date change detection")
        return ChangeDetectionResult(
            suppressed=True,
            suppression_reason="site_visit_change_request",
        )

    # Compute Q&A guard flag
    is_qna_no_change = context.has_qna_question or context.llm_is_question or context.llm_general_qna

    logger.debug("[Step1][CHANGE_DETECT] user_info.date=%s, user_info.event_date=%s",
                user_info.get('date'), user_info.get('event_date'))
    logger.debug("[Step1][CHANGE_DETECT] is_change=%s, change_type=%s",
                enhanced_result.is_change, change_type)
    logger.debug("[Step1][CHANGE_DETECT] message_text=%s...",
                message_text[:100] if message_text else 'None')

    return ChangeDetectionResult(
        change_type=change_type,
        is_qna_no_change=is_qna_no_change,
    )


def compute_routing_decision(
    change_type: Any,  # ChangeType enum
    event_entry: Dict[str, Any],
    previous_step: int,
    in_billing_flow: bool,
) -> ChangeRoutingDecision:
    """Compute routing decision for a detected change.

    Args:
        change_type: Detected change type
        event_entry: Current event record
        previous_step: Step before change was detected
        in_billing_flow: Whether in billing flow

    Returns:
        ChangeRoutingDecision with routing parameters
    """
    # Use DAG-based routing
    decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)

    logger.info("[Step1][CHANGE_ROUTING] change_type=%s, previous_step=%s", change_type, previous_step)
    logger.info("[Step1][CHANGE_ROUTING] decision: next_step=%s, caller_step=%s",
               decision.next_step, decision.updated_caller_step)

    result = ChangeRoutingDecision(
        next_step=decision.next_step,
        caller_step=decision.updated_caller_step if event_entry.get("caller_step") is None else None,
    )

    if decision.next_step != previous_step:
        # Handle billing flow detour
        if in_billing_flow and change_type.value == "date":
            result.should_clear_billing_flow = True
            logger.info("[Step1][DETOUR_FIX] Will clear billing flow state for date change detour")

        # Handle room lock based on change type
        if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
            if decision.next_step == 2:
                if change_type.value == "date":
                    # DATE change to Step 2: KEEP locked_room_id, invalidate hashes
                    result.should_clear_date_confirmed = True
                    result.should_clear_offer_hash = True
                else:
                    # REQUIREMENTS change to Step 2: may clear room lock
                    sourced = event_entry.get("sourced_products")
                    if not (sourced and sourced.get("room") == event_entry.get("locked_room_id")):
                        result.should_clear_room_lock = True
                    result.should_clear_date_confirmed = True

            elif decision.next_step == 3:
                # Going to Step 3 for requirements change
                sourced = event_entry.get("sourced_products")
                if not (sourced and sourced.get("room") == event_entry.get("locked_room_id")):
                    result.should_clear_room_lock = True
                result.should_set_change_detour = True

    return result


def should_skip_vague_date_reset(
    has_qna_question: bool,
    date_already_confirmed: bool,
) -> bool:
    """Check if vague date reset should be skipped.

    When Q&A is detected and date is already confirmed, don't reset.
    Example: "Room B looks great. Which rooms are available in February next year?"
    The "February" is for Q&A, not for the main booking flow.

    Args:
        has_qna_question: Whether Q&A question was detected
        date_already_confirmed: Whether date is already confirmed

    Returns:
        True if vague date reset should be skipped
    """
    return has_qna_question and date_already_confirmed
