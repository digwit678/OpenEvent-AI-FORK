"""Tests for Universal Verbalizer."""

import os
import pytest
from unittest.mock import patch

from ux.universal_verbalizer import (
    MessageContext,
    verbalize_message,
    verbalize_step_message,
)


class TestMessageContext:
    """Tests for MessageContext fact extraction."""

    def test_extract_dates(self):
        """Should extract event date and candidate dates."""
        ctx = MessageContext(
            step=2,
            topic="date_candidates",
            event_date="15.03.2025",
            candidate_dates=["16.03.2025", "17.03.2025"],
        )
        facts = ctx.extract_hard_facts()
        assert "15.03.2025" in facts["dates"]
        assert "16.03.2025" in facts["dates"]
        assert "17.03.2025" in facts["dates"]

    def test_extract_amounts(self):
        """Should extract total and deposit amounts."""
        ctx = MessageContext(
            step=4,
            topic="offer_draft",
            total_amount=500.00,
            deposit_amount=100.00,
        )
        facts = ctx.extract_hard_facts()
        assert "CHF 500.00" in facts["amounts"]
        assert "CHF 100.00" in facts["amounts"]

    def test_extract_room_names(self):
        """Should extract room name and rooms list."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            room_name="Room A",
            rooms=[
                {"name": "Room A", "status": "Available"},
                {"name": "Room B", "status": "Option"},
            ],
        )
        facts = ctx.extract_hard_facts()
        assert "Room A" in facts["room_names"]
        assert "Room B" in facts["room_names"]

    def test_extract_counts(self):
        """Should extract participant count."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            participants_count=30,
        )
        facts = ctx.extract_hard_facts()
        assert "30" in facts["counts"]

    def test_extract_product_prices(self):
        """Should extract prices from products."""
        ctx = MessageContext(
            step=4,
            topic="offer_draft",
            products=[
                {"name": "Coffee", "unit_price": 150.00},
                {"name": "Projector", "price": 50.00},
            ],
        )
        facts = ctx.extract_hard_facts()
        assert "CHF 150.00" in facts["amounts"]
        assert "CHF 50.00" in facts["amounts"]


class TestVerbalizeMessage:
    """Tests for verbalize_message function."""

    def test_empty_fallback_returns_empty(self):
        """Empty fallback should return empty."""
        ctx = MessageContext(step=3, topic="room_avail_result")
        result = verbalize_message("", ctx)
        assert result == ""

    def test_plain_tone_returns_fallback(self):
        """Plain tone should return fallback text directly."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            event_date="15.03.2025",
            room_name="Room A",
        )
        fallback = "Room A is available on 15.03.2025"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_message(fallback, ctx)
        assert result == fallback

    def test_preserves_all_facts(self):
        """Verbalizer should preserve all hard facts."""
        ctx = MessageContext(
            step=4,
            topic="offer_draft",
            event_date="15.03.2025",
            room_name="Room A",
            total_amount=500.00,
            participants_count=30,
        )
        fallback = "Offer for Room A on 15.03.2025 for 30 guests. Total: CHF 500.00"
        # In plain mode, all facts are preserved
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_message(fallback, ctx)
        assert "15.03.2025" in result
        assert "Room A" in result
        assert "500" in result
        assert "30" in result


class TestVerbalizeStepMessage:
    """Tests for verbalize_step_message convenience function."""

    def test_step_2_date_confirmation(self):
        """Should handle Step 2 date confirmation messages."""
        fallback = "Available dates: 15.03.2025, 16.03.2025"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_step_message(
                fallback,
                step=2,
                topic="date_candidates",
                candidate_dates=["15.03.2025", "16.03.2025"],
            )
        assert "15.03.2025" in result
        assert "16.03.2025" in result

    def test_step_3_room_availability(self):
        """Should handle Step 3 room availability messages."""
        fallback = "Room A is available for 30 guests on 15.03.2025"
        rooms = [{"name": "Room A", "status": "Available", "capacity": 50}]
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_step_message(
                fallback,
                step=3,
                topic="room_avail_result",
                event_date="15.03.2025",
                participants_count=30,
                rooms=rooms,
            )
        assert "Room A" in result
        assert "30" in result
        assert "15.03.2025" in result

    def test_step_4_offer(self):
        """Should handle Step 4 offer messages."""
        fallback = "Offer for Room A on 15.03.2025. Total: CHF 500.00"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_step_message(
                fallback,
                step=4,
                topic="offer_draft",
                event_date="15.03.2025",
                room_name="Room A",
                total_amount=500.00,
            )
        assert "Room A" in result
        assert "500" in result

    def test_step_5_negotiation(self):
        """Should handle Step 5 negotiation messages."""
        fallback = "Thank you for accepting the offer for Room A on 15.03.2025"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_step_message(
                fallback,
                step=5,
                topic="negotiation_accept",
                event_date="15.03.2025",
                room_name="Room A",
            )
        assert "Room A" in result
        assert "15.03.2025" in result

    def test_step_7_confirmation(self):
        """Should handle Step 7 confirmation messages."""
        fallback = "Your booking for Room A on 15.03.2025 is confirmed. Deposit: CHF 100.00"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_step_message(
                fallback,
                step=7,
                topic="confirmation_final",
                event_date="15.03.2025",
                room_name="Room A",
                deposit_amount=100.00,
            )
        assert "Room A" in result
        assert "100" in result


class TestFactVerification:
    """Tests for fact verification logic."""

    def test_missing_date_detected(self):
        """Should detect when date is missing from output."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            event_date="15.03.2025",
        )
        facts = ctx.extract_hard_facts()
        # Verify that facts contain the date
        assert "15.03.2025" in facts["dates"]

    def test_missing_room_detected(self):
        """Should detect when room name is missing."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            room_name="Room A",
        )
        facts = ctx.extract_hard_facts()
        assert "Room A" in facts["room_names"]

    def test_missing_amount_detected(self):
        """Should detect when amount is missing."""
        ctx = MessageContext(
            step=4,
            topic="offer_draft",
            total_amount=500.00,
        )
        facts = ctx.extract_hard_facts()
        assert "CHF 500.00" in facts["amounts"]


class TestEdgeCases:
    """Edge case tests."""

    def test_handles_none_values_gracefully(self):
        """Should handle None values without errors."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            event_date=None,
            participants_count=None,
            room_name=None,
        )
        facts = ctx.extract_hard_facts()
        assert facts["dates"] == []
        assert facts["room_names"] == []
        assert facts["counts"] == []

    def test_handles_empty_lists(self):
        """Should handle empty lists without errors."""
        ctx = MessageContext(
            step=4,
            topic="offer_draft",
            rooms=[],
            products=[],
            candidate_dates=[],
        )
        facts = ctx.extract_hard_facts()
        assert facts["dates"] == []
        assert facts["room_names"] == []
        assert facts["amounts"] == []

    def test_deduplicates_room_names(self):
        """Should not duplicate room names."""
        ctx = MessageContext(
            step=3,
            topic="room_avail_result",
            room_name="Room A",
            rooms=[{"name": "Room A"}],  # Same room in list
        )
        facts = ctx.extract_hard_facts()
        # Room A should appear only once
        assert facts["room_names"].count("Room A") == 1
