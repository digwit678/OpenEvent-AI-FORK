"""
Pattern detection utilities for Step1 intake.

Extracted from step1_handler.py for better modularity (I1 refactoring).
These functions detect specific message patterns:
- Offer acceptance (user accepting a proposed offer)
- Billing fragments (user providing billing address)

All functions are PURE: no DB access, no state mutation, no workflow dependencies.

NOTE: `_looks_like_gate_confirmation` and `_extract_confirmation_details` remain
in step1_handler.py because they depend on linked_event workflow state.
"""

import re

from .normalization import normalize_quotes
from detection.keywords.buckets import is_confirmation, detect_language


def looks_like_offer_acceptance(text: str) -> bool:
    """
    Heuristic: short, declarative acknowledgements without question marks
    that contain approval verbs.

    Supports multilingual detection (EN, DE, FR, IT, ES) via centralized
    is_confirmation() from detection.keywords.buckets.

    Excludes date confirmations ("We confirm the date...") which should be
    handled by the date confirmation flow, not offer acceptance.
    """

    if not text:
        return False
    normalized = normalize_quotes(text).lower()
    if "?" in normalized:
        return False
    if len(normalized) > 200:
        return False

    # Exclude date-related confirmations (handled by date confirmation flow)
    # Multilingual: date/day/time/datum (EN/DE), jour/date (FR), data/giorno (IT), fecha/día (ES)
    date_confirmation_re = re.compile(
        r"\bconfirm(?:ed|s|é|ato|ado)?\b.*\b(?:date|day|time|datum|jour|data|giorno|fecha|día)\b|"
        r"\b(?:date|day|time|datum|jour|data|giorno|fecha|día)\b.*\bconfirm(?:ed|s|é|ato|ado)?\b",
        re.IGNORECASE
    )
    if date_confirmation_re.search(normalized):
        return False  # This is a date confirmation, not offer acceptance

    # Use centralized multilingual confirmation detection
    language = detect_language(text)
    return is_confirmation(text, language)


def looks_like_billing_fragment(text: str) -> bool:
    """
    Detect if text looks like a billing address fragment.

    Used to identify when user is providing billing information
    vs. making a room selection or other request.
    """

    if not text:
        return False
    lowered = text.lower()
    # "room X" is not billing info
    if lowered.startswith("room "):
        return False
    keywords = (
        "postal", "postcode", "zip", "street", "avenue",
        "road", "switzerland", " ch", "city", "country"
    )
    if any(k in lowered for k in keywords):
        return True
    # Check for digit groups that look like postal codes
    digit_groups = sum(
        1 for token in lowered.replace(",", " ").split()
        if token.isdigit() and len(token) >= 3
    )
    return digit_groups >= 1


__all__ = [
    "looks_like_offer_acceptance",
    "looks_like_billing_fragment",
]
