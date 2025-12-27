"""
Message classification utilities for Step 5 Negotiation.

Extracted from step5_handler.py for better modularity (N2 refactoring).
Contains pure functions for intent detection and message classification.

Usage:
    from .classification import classify_message, collect_detected_intents

    intents = collect_detected_intents("I accept the offer")
    # [("accept", 0.85)]

    intent, confidence = classify_message("I accept the offer")
    # ("accept", 0.85)
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from backend.detection.response.matchers import (
    is_room_selection,
    matches_acceptance_pattern,
    matches_counter_pattern,
    matches_decline_pattern,
)


def collect_detected_intents(message_text: str) -> List[Tuple[str, float]]:
    """
    Detect all possible intents from message text with confidence scores.

    Returns a list of (intent, confidence) tuples for each detected intent.
    Multiple intents can be detected from the same message.

    Recognized intents:
        - room_selection: Client is choosing a room
        - accept: Client is accepting the offer
        - decline: Client is declining the offer
        - counter: Client is making a counter-proposal
        - clarification: Client is asking a question
    """
    lowered = (message_text or "").lower()
    intents: List[Tuple[str, float]] = []

    if is_room_selection(lowered):
        intents.append(("room_selection", 0.85))

    accept, accept_conf, _ = matches_acceptance_pattern(lowered)
    if accept:
        intents.append(("accept", accept_conf))

    decline, decline_conf, _ = matches_decline_pattern(lowered)
    if decline:
        intents.append(("decline", decline_conf))

    counter, counter_conf, _ = matches_counter_pattern(lowered)
    if counter:
        intents.append(("counter", counter_conf))

    if re.search(r"\bchf\s*\d", lowered) or re.search(r"\d+\s*(?:franc|price|total)", lowered):
        intents.append(("counter", 0.65))

    if "?" in lowered:
        intents.append(("clarification", 0.6))

    return intents


def classify_message(message_text: str) -> Tuple[str, float]:
    """
    Classify a message into a single primary intent with confidence.

    Returns the highest-confidence intent from collect_detected_intents,
    or ("clarification", 0.3) as the default fallback.

    Returns:
        Tuple of (intent_name, confidence_score)
    """
    lowered = (message_text or "").lower()
    candidates = collect_detected_intents(lowered)

    if candidates:
        best = max(candidates, key=lambda item: item[1])
        if best[1] > 0.4:
            return best

    if "?" in lowered:
        return "clarification", 0.6

    return "clarification", 0.3


def iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    """
    Convert ISO date format (YYYY-MM-DD) to DD.MM.YYYY format.

    Args:
        raw: Date string in YYYY-MM-DD format

    Returns:
        Date string in DD.MM.YYYY format, or None if invalid/empty
    """
    if not raw:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not match:
        return None
    year, month, day = match.groups()
    return f"{day}.{month}.{year}"


__all__ = [
    "collect_detected_intents",
    "classify_message",
    "iso_to_ddmmyyyy",
]
