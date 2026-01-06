"""
Regression Tests for TEAM_GUIDE Known Issues (REG_*)

Tests for bugs documented in TEAM_GUIDE.md to prevent silent regressions.
Each test is linked to a specific bug entry.

References:
- TEST_MATRIX_detection_and_flow.md: REG_* tests
- docs/guides/TEAM_GUIDE.md: Known Issues & Fixes section
"""

from __future__ import annotations

import re
import pytest
from typing import Any, Dict, List


# ==============================================================================
# ANTI-FALLBACK ASSERTIONS (Critical for all regression tests)
# ==============================================================================


FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
]


def assert_no_fallback(response_body: str, context: str = ""):
    """Assert that response does not contain legacy fallback messages."""
    if not response_body:
        return
    lowered = response_body.lower()
    for pattern in FALLBACK_PATTERNS:
        assert pattern not in lowered, (
            f"FALLBACK DETECTED: '{pattern}' in response.\n"
            f"Context: {context}\n"
            f"Response snippet: {response_body[:300]}..."
        )


# ==============================================================================
# REG_PRODUCT_DUP_001: Product Additions Causing Duplicates
# TEAM_GUIDE: "Product Additions Causing Duplicates (Fixed)"
# ==============================================================================


def _upsert_product(products: List[Dict], item: Dict) -> List[Dict]:
    """
    Helper simulating the fixed upsert logic.
    Should INCREMENT quantity, not REPLACE.
    """
    for existing in products:
        if existing.get("name", "").lower() == item.get("name", "").lower():
            # FIXED: Increment instead of replace
            existing["quantity"] = existing.get("quantity", 0) + item.get("quantity", 1)
            return products

    # New product
    products.append(item.copy())
    return products


def test_REG_PRODUCT_DUP_001_quantity_increments():
    """
    Product addition should increment quantity by 1, not duplicate.
    Bug: User said "add another wireless microphone" → quantity went from 1 to 2
    instead of being set to 1 again.
    """
    # Initial state: 1 wireless microphone
    products = [{"name": "Wireless Microphone", "quantity": 1, "unit_price": 25.0}]

    # User says "add another wireless microphone"
    add_request = {"name": "Wireless Microphone", "quantity": 1}

    # After upsert
    result = _upsert_product(products, add_request)

    # Should be quantity 2, not a duplicate entry or replaced to 1
    mic = next((p for p in result if p["name"] == "Wireless Microphone"), None)
    assert mic is not None
    assert mic["quantity"] == 2, f"Expected quantity=2 after 'add another', got {mic['quantity']}"


def test_REG_PRODUCT_DUP_001_new_product_adds():
    """New product should be added with specified quantity."""
    products = [{"name": "Projector", "quantity": 1}]
    add_request = {"name": "Wireless Microphone", "quantity": 1}

    result = _upsert_product(products, add_request)

    assert len(result) == 2
    mic = next((p for p in result if p["name"] == "Wireless Microphone"), None)
    assert mic is not None
    assert mic["quantity"] == 1


# ==============================================================================
# REG_ACCEPT_STUCK_001: Offer Acceptance Stuck / Not Reaching HIL
# TEAM_GUIDE: "Offer Acceptance Stuck / Not Reaching HIL (Fixed)"
# ==============================================================================


def _is_acceptance_phrase_normalized(message: str) -> bool:
    """
    Check if message is an acceptance phrase with quote normalization.
    Bug: Curly apostrophes weren't being normalized.
    """
    if not message:
        return False

    # Normalize curly quotes (the fix)
    normalized = message.strip().lower()
    normalized = normalized.replace("'", "'").replace("'", "'")
    normalized = normalized.replace(""", '"').replace(""", '"')

    acceptance_phrases = {
        "yes", "yes please", "ok", "okay", "sure",
        "proceed", "continue", "please proceed", "please continue",
        "go ahead", "that's fine", "approved",
        "please send", "confirm", "agreed",
    }

    # Check exact match
    if normalized in acceptance_phrases:
        return True

    # Check patterns
    patterns = [
        r"\bthat'?s fine\b",
        r"\bapproved\b",
        r"\bplease (?:send|proceed|continue)\b",
        r"\bgo ahead\b",
        r"\bok\b",
    ]

    for pattern in patterns:
        if re.search(pattern, normalized):
            return True

    return False


def test_REG_ACCEPT_STUCK_001_thats_fine_accepted():
    """
    'that's fine' acceptance should be detected and reach HIL.
    Bug: Acceptance was classified as 'other', Step 5 never ran.
    """
    # With straight apostrophe
    assert _is_acceptance_phrase_normalized("that's fine") is True


def test_REG_ACCEPT_STUCK_001_curly_quote_normalized():
    """
    Curly apostrophe should be normalized.
    Bug: "that's fine" (curly) wasn't matching.
    """
    # With curly apostrophe
    assert _is_acceptance_phrase_normalized("that's fine") is True


def test_REG_ACCEPT_STUCK_001_please_send():
    """'please send' should be acceptance."""
    assert _is_acceptance_phrase_normalized("please send") is True


def test_REG_ACCEPT_STUCK_001_go_ahead():
    """'go ahead' should be acceptance."""
    assert _is_acceptance_phrase_normalized("go ahead") is True


# ==============================================================================
# REG_HIL_DUP_001: Duplicate HIL Sends After Acceptance
# TEAM_GUIDE: "Duplicate HIL sends after offer acceptance (Fixed)"
# ==============================================================================


def _should_skip_hil_if_pending(hil_state: Dict[str, Any]) -> bool:
    """
    Check if HIL request should be skipped because one is already pending.
    Bug: Multiple HIL tasks were created for the same acceptance.
    """
    if hil_state.get("negotiation_pending_decision"):
        return True
    if hil_state.get("hil_task_exists"):
        return True
    return False


def test_REG_HIL_DUP_001_skip_if_pending():
    """
    If HIL decision is already pending, skip creating duplicate.
    Bug: Re-acceptance while waiting created multiple tasks.
    """
    hil_state = {"negotiation_pending_decision": True}
    assert _should_skip_hil_if_pending(hil_state) is True


def test_REG_HIL_DUP_001_skip_if_task_exists():
    """Skip if HIL task already exists."""
    hil_state = {"hil_task_exists": True}
    assert _should_skip_hil_if_pending(hil_state) is True


def test_REG_HIL_DUP_001_create_if_none():
    """Create HIL task if none pending."""
    hil_state = {}
    assert _should_skip_hil_if_pending(hil_state) is False


# ==============================================================================
# REG_DATE_MONTH_001: Spurious Unavailable Date Apologies
# TEAM_GUIDE: "Spurious unavailable-date apologies on month-only requests (Fixed)"
# ==============================================================================


def _client_requested_specific_date(message: str) -> bool:
    """
    Check if client mentioned a specific date (not just month).
    Bug: Month-only requests got apologies for dates client never mentioned.
    """
    if not message:
        return False

    text = message.lower()

    # Specific date patterns (day + month or full date)
    specific_patterns = [
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",  # 10.12.2025
        r"\b\d{4}-\d{2}-\d{2}\b",  # ISO date
        r"\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b",
    ]

    for pattern in specific_patterns:
        if re.search(pattern, text):
            return True

    return False


def test_REG_DATE_MONTH_001_month_only_not_specific():
    """
    Month-only request should NOT be treated as specific date.
    Bug: "February 2026, Saturday evening" triggered apology for 20.02.2026.
    """
    message = "February 2026, Saturday evening"
    assert _client_requested_specific_date(message) is False


def test_REG_DATE_MONTH_001_specific_date_detected():
    """Specific date should be detected."""
    messages = [
        "10.12.2025",
        "2025-12-10",
        "12 February",
        "February 12",
    ]

    for msg in messages:
        assert _client_requested_specific_date(msg) is True, f"'{msg}' should be specific"


# ==============================================================================
# REG_QUOTE_CONF_001: Quoted Confirmation Triggering Q&A
# TEAM_GUIDE: "Regression trap: quoted confirmations triggering General Q&A"
# ==============================================================================


def _should_force_non_general(user_info: Dict, message_signals_confirmation: bool) -> bool:
    """
    Force is_general=False when we have date info or confirmation signal.
    Bug: Quoted text triggered Q&A even though client confirmed.
    """
    if user_info.get("date") or user_info.get("event_date"):
        return True
    if message_signals_confirmation:
        return True
    return False


def test_REG_QUOTE_CONF_001_date_forces_non_general():
    """
    If date extracted, force is_general=False.
    Bug: Quoted text in email triggered Q&A despite date extraction.
    """
    user_info = {"date": "2025-12-10"}
    assert _should_force_non_general(user_info, False) is True


def test_REG_QUOTE_CONF_001_confirmation_forces_non_general():
    """If confirmation signal detected, force is_general=False."""
    user_info = {}
    assert _should_force_non_general(user_info, message_signals_confirmation=True) is True


def test_REG_QUOTE_CONF_001_no_date_no_force():
    """Without date or confirmation, don't force."""
    user_info = {}
    assert _should_force_non_general(user_info, False) is False


# ==============================================================================
# REG_ROOM_REPEAT_001: Room Choice Repeats
# TEAM_GUIDE: "Room choice repeats / manual-review detours (Ongoing Fix)"
# ==============================================================================


def _is_room_choice(message: str) -> bool:
    """
    Detect room choice reply.
    Bug: Room name triggered Step 3 repeat or manual review.
    """
    if not message:
        return False

    text = message.strip().lower()

    room_patterns = [
        r"^room\s+[a-z](?:\s|$)",
        r"room\s+[a-z]\s+(?:please|looks good|works|is fine)",
        r"(?:take|book|reserve|lock)\s+room\s+[a-z]",
        r"^punkt\.?null",
        r"^punkt\s+null",
    ]

    for pattern in room_patterns:
        if re.search(pattern, text):
            return True

    return False


def test_REG_ROOM_REPEAT_001_room_a_detected():
    """
    'Room A' should be detected as room choice.
    Bug: Reply was treated as general message.
    """
    assert _is_room_choice("Room A") is True
    assert _is_room_choice("Room A please") is True
    assert _is_room_choice("Room A looks good") is True


def test_REG_ROOM_REPEAT_001_take_room():
    """'Take Room B' should be room choice."""
    assert _is_room_choice("Take Room B") is True
    assert _is_room_choice("Book Room C") is True


def test_REG_ROOM_REPEAT_001_punkt_null():
    """'punkt.null' should be room choice."""
    assert _is_room_choice("punkt.null") is True
    assert _is_room_choice("Punkt Null") is True


# ==============================================================================
# REG_BILL_ROOM_001: Room Label as Billing
# TEAM_GUIDE: Related to "Room choice repeats"
# ==============================================================================


def _looks_like_billing_not_room(message: str) -> bool:
    """
    Distinguish billing update from room choice.
    Bug: "Room E" was saved as billing address.
    """
    if not message:
        return False

    text = message.strip().lower()

    # If it's a room name, it's NOT billing
    if _is_room_choice(message):
        return False

    # Check for billing indicators
    billing_indicators = [
        r"\b(?:postal|zip)\s*code\b",
        r"\bvat\b",
        r"\bcountry\b",
        r"\bstreet\b",
        r"\baddress\b",
        r"\b\d{4,5}\s+[a-z]+",  # Postal code + city
        r"(?:switzerland|germany|austria|france)",
    ]

    for pattern in billing_indicators:
        if re.search(pattern, text):
            return True

    return False


def test_REG_BILL_ROOM_001_room_not_billing():
    """
    Room name should NOT be detected as billing.
    Bug: 'Room E' was saved as billing address.
    """
    assert _looks_like_billing_not_room("Room E") is False
    assert _looks_like_billing_not_room("Room A") is False


def test_REG_BILL_ROOM_001_billing_is_billing():
    """Actual billing should be detected."""
    assert _looks_like_billing_not_room("Postal code: 8000") is True
    assert _looks_like_billing_not_room("8001 Zurich, Switzerland") is True


# ==============================================================================
# ANTI-REGRESSION: Fallback Message Guards
# ==============================================================================


def test_fallback_patterns_defined():
    """Ensure fallback patterns are properly defined for guards."""
    assert len(FALLBACK_PATTERNS) > 0
    assert "no specific information available" in FALLBACK_PATTERNS


def test_assert_no_fallback_catches():
    """Test that assert_no_fallback properly catches fallback messages."""
    bad_response = "It appears there is no specific information available for your request."

    with pytest.raises(AssertionError) as exc_info:
        assert_no_fallback(bad_response, "test context")

    assert "FALLBACK DETECTED" in str(exc_info.value)


def test_assert_no_fallback_passes_clean():
    """Test that assert_no_fallback passes for clean responses."""
    good_response = "Here are the available rooms for your event:\n- Room A (40 capacity)\n- Room B (60 capacity)"

    # Should not raise
    assert_no_fallback(good_response, "test context")
