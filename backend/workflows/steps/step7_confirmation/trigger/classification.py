"""Message classification for Step 7 confirmation.

Extracted from step7_handler.py as part of F1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Any, Dict

from .constants import (
    CONFIRM_KEYWORDS,
    RESERVE_KEYWORDS,
    VISIT_KEYWORDS,
    DECLINE_KEYWORDS,
    CHANGE_KEYWORDS,
    QUESTION_KEYWORDS,
)
from .helpers import any_keyword_match, contains_word


def classify_message(message_text: str, event_entry: Dict[str, Any]) -> str:
    """Classify client message intent for Step 7 routing.

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

    # Keyword-based classification
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
