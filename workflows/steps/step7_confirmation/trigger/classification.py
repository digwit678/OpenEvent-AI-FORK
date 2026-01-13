"""Message classification for Step 7 confirmation.

Extracted from step7_handler.py as part of F1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .constants import (
    CONFIRM_KEYWORDS,
    RESERVE_KEYWORDS,
    VISIT_KEYWORDS,
    DECLINE_KEYWORDS,
    CHANGE_KEYWORDS,
    QUESTION_KEYWORDS,
)
from .helpers import any_keyword_match, contains_word


def classify_message(
    message_text: str,
    event_entry: Dict[str, Any],
    unified_detection: Optional[Any] = None,
) -> str:
    """Classify client message intent for Step 7 routing.

    Args:
        message_text: The client message text
        event_entry: Current event state
        unified_detection: Optional unified detection result from LLM

    Returns one of: 'confirm', 'deposit_paid', 'site_visit', 'reserve',
                    'decline', 'change', 'question'
    """
    lowered = message_text.lower()

    # Check deposit payment first (context-dependent)
    deposit_state = event_entry.get("deposit_state") or {}
    if deposit_state.get("status") in {"requested", "awaiting_payment"}:
        if contains_word(lowered, "deposit") and any(
            contains_word(lowered, token) for token in ("paid", "sent", "transferred", "settled")
        ):
            return "deposit_paid"

    # -------------------------------------------------------------------------
    # FIX: Check unified detection for site_visit_request FIRST
    # This fixes the bug where "Yes, can we visit next week?" returns "confirm"
    # because CONFIRM_KEYWORDS ("yes") is checked before VISIT_KEYWORDS
    # -------------------------------------------------------------------------
    if unified_detection:
        qna_types = getattr(unified_detection, "qna_types", []) or []
        if "site_visit_request" in qna_types or "site_visit_overview" in qna_types:
            return "site_visit"

    # Check site visit state - if proposed, prioritize site visit keywords
    site_visit_state = event_entry.get("site_visit_state") or {}
    if site_visit_state.get("status") == "proposed":
        if any_keyword_match(lowered, VISIT_KEYWORDS):
            return "site_visit"

    # Keyword-based classification (original order for non-site-visit cases)
    if any_keyword_match(lowered, CONFIRM_KEYWORDS):
        return "confirm"
    if any_keyword_match(lowered, VISIT_KEYWORDS):
        return "site_visit"
    if any_keyword_match(lowered, RESERVE_KEYWORDS):
        return "reserve"
    if any_keyword_match(lowered, DECLINE_KEYWORDS):
        return "decline"
    if any_keyword_match(lowered, CHANGE_KEYWORDS):
        return "change"
    if "?" in lowered or any(token in lowered for token in QUESTION_KEYWORDS):
        return "question"
    return "question"
