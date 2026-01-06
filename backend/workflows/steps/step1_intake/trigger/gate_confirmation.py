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


def looks_like_offer_acceptance(text: str) -> bool:
    """
    Heuristic: short, declarative acknowledgements without question marks
    that contain approval verbs.

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
    date_confirmation_re = re.compile(
        r"\bconfirm(?:ed|s)?\b.*\b(?:date|day|time|datum)\b|"
        r"\b(?:date|day|time|datum)\b.*\bconfirm(?:ed|s)?\b",
        re.IGNORECASE
    )
    if date_confirmation_re.search(normalized):
        return False  # This is a date confirmation, not offer acceptance

    accept_re = re.compile(
        r"\b("
        r"accept(?:ed)?|"
        r"approv(?:e|ed|al)|"
        r"confirm(?:ed)?|"
        r"proceed|continue|go ahead|"
        r"send (?:it|to client)|please send|ok to send|"
        r"all good|looks good|sounds good|good to go|"
        r"(?:that'?s|thats) fine|fine for me"
        r")\b"
    )
    if accept_re.search(normalized):
        return True

    # Fallback to legacy tokens for odd phrasing.
    accept_tokens = (
        "accept",
        "accepted",
        "confirm",
        "confirmed",
        "approve",
        "approved",
        "continue",
        "please send",
        "send it",
        "send to client",
        "ok to send",
        "go ahead",
        "proceed",
        "that's fine",
        "thats fine",
        "fine for me",
        "sounds good",
        "good to go",
        "ok thats fine",
        "ok that's fine",
        "all good",
    )
    return any(token in normalized for token in accept_tokens)


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
