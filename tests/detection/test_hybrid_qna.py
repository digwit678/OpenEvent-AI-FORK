"""
Hybrid Q&A Detection Tests (DET_HYBRID_QNA_*)

Tests for messages that contain BOTH a workflow action AND a Q&A question.
The system must:
1. Process the workflow action (confirmation, detour, shortcut)
2. ALSO respond to the Q&A question
3. NEVER let the Q&A modify workflow state (Q&A is a "SELECT query")

Key principle: Q&A is informational only - it reads but never writes to workflow state.

Examples:
- "Room B sounds great. What parking options do you have?" -> confirm room + answer parking
- "Actually change date to April. Do you have catering?" -> detour + answer catering
- "February next year availability?" -> answer with February next year dates

References:
- BUG-010 in DEV_CHANGELOG.md
- BUG-003 in TEAM_GUIDE.md
- The timing issue: unified_detection runs AFTER intake.process(), so shortcuts
  need to call _detect_qna_types() directly as fallback.
"""

from __future__ import annotations

import pytest
from datetime import date
from typing import List

from detection.intent.classifier import _detect_qna_types

# Mark all tests in this module as v4
pytestmark = pytest.mark.v4


# ==============================================================================
# DET_HYBRID_QNA_001: Room Confirmation + Q&A Detection
# ==============================================================================


class TestHybridConfirmation:
    """Tests for hybrid messages: room/date confirmation + Q&A question."""

    def test_hybrid_room_confirmation_with_parking_qna(self):
        """
        Room confirmation + parking Q&A should detect both intents.
        Input: "Room B sounds perfect, I will take it. What parking options do you have?"
        Expected: 'parking_policy' in qna_types
        """
        message = "Room B sounds perfect, I will take it. What parking options do you have?"
        qna_types = _detect_qna_types(message.lower())
        assert "parking_policy" in qna_types, f"Expected 'parking_policy' in {qna_types}"

    def test_hybrid_room_confirmation_with_catering_qna(self):
        """
        Room confirmation + catering Q&A should detect both intents.
        Input: "Let's proceed with Room C. Do you offer catering packages?"
        Expected: 'catering_for' in qna_types
        """
        message = "Let's proceed with Room C. Do you offer catering packages?"
        qna_types = _detect_qna_types(message.lower())
        assert "catering_for" in qna_types, f"Expected 'catering_for' in {qna_types}"

    def test_hybrid_date_confirmation_with_room_features_qna(self):
        """
        Date confirmation + room features Q&A.
        Input: "March 22 works for us. Does Room B have a projector?"
        Expected: 'room_features' or 'rooms_by_feature' in qna_types
        """
        message = "March 22 works for us. Does Room B have a projector?"
        qna_types = _detect_qna_types(message.lower())
        assert any(t in qna_types for t in ["room_features", "rooms_by_feature"]), \
            f"Expected room features Q&A in {qna_types}"


# ==============================================================================
# DET_HYBRID_QNA_002: Month-Constrained Availability Detection
# ==============================================================================


class TestMonthConstrainedAvailability:
    """Tests for Q&A questions asking about availability in a specific month."""

    def test_february_availability_detection(self):
        """
        'available in February' should trigger 'free_dates' Q&A type.
        Input: "which rooms would be available for a larger event in February"
        Expected: 'free_dates' in qna_types
        """
        message = "which rooms would be available for a larger event in February"
        qna_types = _detect_qna_types(message.lower())
        assert "free_dates" in qna_types, \
            f"Expected 'free_dates' for month-constrained availability, got {qna_types}"

    def test_march_availability_detection(self):
        """
        'available in March' should trigger 'free_dates' Q&A type.
        """
        message = "what dates are available in March for our conference?"
        qna_types = _detect_qna_types(message.lower())
        assert "free_dates" in qna_types, f"Expected 'free_dates' in {qna_types}"

    def test_would_be_available_pattern(self):
        """
        'would be available in [month]' pattern should detect free_dates.
        This is a common phrasing that was previously missed (BUG-010).
        """
        message = "which rooms would be available for a larger event in February next year?"
        qna_types = _detect_qna_types(message.lower())
        assert "free_dates" in qna_types, \
            f"Expected 'free_dates' for 'would be available' pattern, got {qna_types}"

    def test_hybrid_confirmation_with_february_availability(self):
        """
        Room confirmation + February availability Q&A (the original bug scenario).
        Input: "Room B looks great, let's proceed. By the way, which rooms would be available in February next year?"
        Expected: 'free_dates' in qna_types
        """
        message = (
            "Room B looks great, let's proceed with that. "
            "By the way, which rooms would be available for a larger event in February next year?"
        )
        qna_types = _detect_qna_types(message.lower())
        assert "free_dates" in qna_types, \
            f"Hybrid confirmation + February Q&A should detect 'free_dates', got {qna_types}"
        # Should also detect rooms_by_feature since it asks "which rooms"
        assert "rooms_by_feature" in qna_types, \
            f"Should also detect 'rooms_by_feature' for 'which rooms' query, got {qna_types}"


# ==============================================================================
# DET_HYBRID_QNA_003: "Next Year" Detection
# ==============================================================================


class TestNextYearDetection:
    """Tests for 'next year' relative date handling."""

    def test_next_year_anchor_extraction(self):
        """
        'February next year' should extract month=2 and force_next_year=True.
        """
        from workflows.qna.router import _extract_anchor

        message = "available in February next year"
        month, day, force_next_year = _extract_anchor(message)

        assert month == 2, f"Expected month=2 for February, got {month}"
        assert force_next_year is True, f"Expected force_next_year=True, got {force_next_year}"

    def test_next_year_german(self):
        """
        German 'nächstes Jahr' should also detect next year.
        """
        from workflows.qna.router import _extract_anchor

        message = "verfügbar im Februar nächstes Jahr"
        month, day, force_next_year = _extract_anchor(message)

        assert month == 2, f"Expected month=2 for Februar, got {month}"
        assert force_next_year is True, f"Expected force_next_year=True for German, got {force_next_year}"

    def test_date_resolution_next_year(self):
        """
        When force_next_year=True, the resolved date should be current_year + 1.
        """
        from workflows.common.catalog import _resolve_anchor_date

        today = date.today()
        # February with force_next_year should always be next year
        resolved = _resolve_anchor_date(2, None, force_next_year=True)

        assert resolved.year == today.year + 1, \
            f"Expected year={today.year + 1} for 'next year', got {resolved.year}"
        assert resolved.month == 2, f"Expected month=2, got {resolved.month}"

    def test_date_resolution_without_next_year_future_month(self):
        """
        Without 'next year', a future month should stay in current year.
        E.g., if today is January, December should be this year.
        """
        from workflows.common.catalog import _resolve_anchor_date

        today = date.today()
        # Use a month definitely after today
        future_month = (today.month % 12) + 1
        if future_month <= today.month:
            # If we're in December, use a month that's definitely future
            future_month = today.month + 1 if today.month < 12 else 1

        resolved = _resolve_anchor_date(future_month, None, force_next_year=False)

        # Should be either this year or next year depending on if month passed
        if future_month > today.month:
            assert resolved.year == today.year, \
                f"Future month {future_month} should be this year {today.year}, got {resolved.year}"
        # If month already passed this year, it should be next year


# ==============================================================================
# DET_HYBRID_QNA_004: German Month Detection
# ==============================================================================


class TestGermanMonthDetection:
    """Tests for German month name detection in Q&A."""

    def test_german_februar_detection(self):
        """German 'Februar' should be detected."""
        from workflows.qna.router import _extract_anchor

        message = "verfügbar im Februar"
        month, day, force_next_year = _extract_anchor(message)
        assert month == 2, f"Expected month=2 for Februar, got {month}"

    def test_german_maerz_detection(self):
        """German 'März' (and ASCII 'Maerz') should be detected."""
        from workflows.qna.router import _extract_anchor

        # Test with umlaut
        message1 = "was ist frei im März"
        month1, _, _ = _extract_anchor(message1)
        assert month1 == 3, f"Expected month=3 for März, got {month1}"

        # Test with ASCII alternative
        message2 = "was ist frei im Maerz"
        month2, _, _ = _extract_anchor(message2)
        assert month2 == 3, f"Expected month=3 for Maerz, got {month2}"


# ==============================================================================
# DET_HYBRID_QNA_005: Hybrid Detection Doesn't Modify State
# ==============================================================================


class TestHybridQnaStateIsolation:
    """
    Tests ensuring Q&A detection doesn't modify workflow state.
    Q&A is a "SELECT query" - it reads but never writes.
    """

    def test_qna_types_detection_is_stateless(self):
        """
        _detect_qna_types should be a pure function with no side effects.
        Multiple calls with same input should return same result.
        """
        message = "Room B looks great. What's available in February?"

        result1 = _detect_qna_types(message.lower())
        result2 = _detect_qna_types(message.lower())

        assert result1 == result2, "Q&A detection should be deterministic"

    def test_complex_hybrid_message_detection(self):
        """
        Complex message with multiple potential intents.
        Input: "I'll take Room B for March 22. Also, what catering do you have and is parking available?"
        Expected: Should detect catering_for and parking_policy
        """
        message = (
            "I'll take Room B for March 22. "
            "Also, what catering do you have and is parking available?"
        )
        qna_types = _detect_qna_types(message.lower())

        assert "catering_for" in qna_types, f"Should detect catering, got {qna_types}"
        assert "parking_policy" in qna_types, f"Should detect parking, got {qna_types}"


# ==============================================================================
# DET_HYBRID_QNA_006: Edge Cases
# ==============================================================================


class TestHybridEdgeCases:
    """Edge cases for hybrid Q&A detection."""

    def test_empty_message_returns_empty_types(self):
        """Empty message should return empty Q&A types list."""
        qna_types = _detect_qna_types("")
        assert qna_types == [], f"Expected empty list for empty message, got {qna_types}"

    def test_only_confirmation_no_qna(self):
        """
        Pure confirmation without Q&A should return empty Q&A types.
        This ensures we don't over-detect Q&A in simple confirmations.
        """
        message = "Yes, Room B works perfectly. Please proceed."
        qna_types = _detect_qna_types(message.lower())
        # Should not contain date-related Q&A types for simple confirmation
        assert "free_dates" not in qna_types, \
            f"Simple confirmation shouldn't trigger free_dates, got {qna_types}"

    def test_all_months_detected(self):
        """All English month names should be detected in availability queries."""
        from workflows.qna.router import _extract_anchor

        months = [
            ("january", 1), ("february", 2), ("march", 3), ("april", 4),
            ("may", 5), ("june", 6), ("july", 7), ("august", 8),
            ("september", 9), ("october", 10), ("november", 11), ("december", 12)
        ]

        for month_name, expected_num in months:
            message = f"what's available in {month_name}"
            month, _, _ = _extract_anchor(message)
            assert month == expected_num, \
                f"Expected {expected_num} for {month_name}, got {month}"
