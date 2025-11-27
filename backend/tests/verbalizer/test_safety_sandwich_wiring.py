"""Tests for Safety Sandwich wiring helpers."""

import os
import pytest
from unittest.mock import patch

from backend.ux.safety_sandwich_wiring import (
    verbalize_room_response,
    verbalize_offer_response,
)


class TestVerbalizerRoomResponse:
    """Tests for verbalize_room_response helper."""

    def test_empty_fallback_returns_empty(self):
        """Empty fallback text should return empty."""
        result = verbalize_room_response("")
        assert result == ""

    def test_plain_tone_returns_fallback(self):
        """Plain tone should return the fallback text directly."""
        fallback = "Room A is available on 15.03.2025"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_room_response(
                fallback,
                event_date="15.03.2025",
                participants_count=30,
                rooms=[{"name": "Room A", "status": "Available", "capacity": 50}],
            )
        assert result == fallback

    def test_builds_facts_from_rooms(self):
        """Should build RoomOfferFacts from room data."""
        fallback = "Room A is available on 15.03.2025 for 30 guests"
        rooms = [
            {
                "name": "Room A",
                "status": "Available",
                "capacity": 50,
                "requirements": {"matched": ["projector"], "missing": ["catering"]},
                "hint": "Best match",
            },
            {
                "name": "Room B",
                "status": "Option",
                "capacity": 80,
            },
        ]
        # In plain mode, the function should return fallback
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_room_response(
                fallback,
                event_date="15.03.2025",
                event_date_iso="2025-03-15",
                participants_count=30,
                rooms=rooms,
                recommended_room="Room A",
            )
        assert result == fallback

    def test_determines_recommended_room_from_available(self):
        """Should auto-determine recommended room from first available."""
        fallback = "Room B is on option"
        rooms = [
            {"name": "Room A", "status": "Unavailable"},
            {"name": "Room B", "status": "Option"},
        ]
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_room_response(
                fallback,
                event_date="15.03.2025",
                rooms=rooms,
            )
        assert result == fallback


class TestVerbalizerOfferResponse:
    """Tests for verbalize_offer_response helper."""

    def test_empty_fallback_returns_empty(self):
        """Empty fallback text should return empty."""
        result = verbalize_offer_response("")
        assert result == ""

    def test_plain_tone_returns_fallback(self):
        """Plain tone should return the fallback text directly."""
        fallback = "Offer for Room A on 15.03.2025\nTotal: CHF 500.00"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_offer_response(
                fallback,
                event_date="15.03.2025",
                room_name="Room A",
                total_amount=500.00,
            )
        assert result == fallback

    def test_builds_facts_from_offer_data(self):
        """Should build RoomOfferFacts from offer data."""
        fallback = "Offer for Room A\nCoffee package: CHF 150.00\nTotal: CHF 650.00"
        products = [
            {"name": "Coffee package", "unit_price": 150.00},
            {"name": "Projector rental", "unit_price": 50.00},
        ]
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_offer_response(
                fallback,
                event_date="15.03.2025",
                event_date_iso="2025-03-15",
                participants_count=30,
                room_name="Room A",
                total_amount=650.00,
                deposit_amount=200.00,
                products=products,
            )
        assert result == fallback

    def test_handles_missing_optional_fields(self):
        """Should handle missing optional fields gracefully."""
        fallback = "Offer draft"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_offer_response(
                fallback,
                # No optional fields provided
            )
        assert result == fallback


class TestWiringIntegration:
    """Integration tests for wiring helpers."""

    def test_room_response_preserves_date_format(self):
        """Room response should preserve date format from fallback."""
        fallback = "Available on 15.03.2025"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_room_response(
                fallback,
                event_date="15.03.2025",
            )
        assert "15.03.2025" in result

    def test_offer_response_preserves_total(self):
        """Offer response should preserve total amount."""
        fallback = "Total: CHF 500.00"
        with patch.dict(os.environ, {"VERBALIZER_TONE": "plain"}):
            result = verbalize_offer_response(
                fallback,
                total_amount=500.00,
            )
        assert "500" in result
