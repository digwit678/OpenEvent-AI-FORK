"""
Tests for DAG-based change propagation logic.

These tests verify that when a confirmed/captured variable is updated,
ONLY the dependent steps re-run per the v4 DAG change matrix.
"""

from __future__ import annotations

import pytest

from workflows.change_propagation import (
    ChangeType,
    NextStepDecision,
    route_change_on_updated_variable,
    detect_change_type,
    should_skip_step3_after_date_change,
    compute_offer_hash,
)


@pytest.mark.v4
class TestRouteChangeOnUpdatedVariable:
    """Test the main routing function for all change types."""

    def test_date_change_routes_to_step2(self):
        """DATE change → Step 2, with maybe_run_step3=True."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "chosen_date": "2026-03-10",
            "date_confirmed": True,
            "locked_room_id": "RoomA",
            "requirements_hash": "hash123",
            "room_eval_hash": "hash123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.DATE, from_step=4)

        assert decision.next_step == 2
        assert decision.maybe_run_step3 is True
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_room_change_routes_to_step3(self):
        """ROOM change → Step 3, no maybe_run_step3."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "chosen_date": "2026-03-10",
            "date_confirmed": True,
            "locked_room_id": "RoomA",
            "requirements_hash": "hash123",
            "room_eval_hash": "hash123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.ROOM, from_step=4)

        assert decision.next_step == 3
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_requirements_change_routes_to_step3_when_hash_mismatch(self):
        """REQUIREMENTS change with hash mismatch → Step 3."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "locked_room_id": "RoomA",
            "requirements_hash": "hash_new",
            "room_eval_hash": "hash_old",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=4)

        assert decision.next_step == 3
        assert decision.updated_caller_step == 4
        assert decision.needs_reeval is True

    def test_requirements_change_skips_when_hash_matches(self):
        """REQUIREMENTS change with matching hash → fast-skip to caller."""
        event_state = {
            "current_step": 3,
            "caller_step": 4,
            "locked_room_id": "RoomA",
            "requirements_hash": "hash123",
            "room_eval_hash": "hash123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS, from_step=3)

        assert decision.next_step == 4  # Return to caller
        assert decision.maybe_run_step3 is False
        assert decision.skip_reason == "requirements_hash_match"
        assert decision.needs_reeval is False

    def test_products_change_stays_in_step4(self):
        """PRODUCTS change → Stay in Step 4, no structural dependencies."""
        event_state = {
            "current_step": 4,
            "caller_step": None,
            "locked_room_id": "RoomA",
            "requirements_hash": "hash123",
            "room_eval_hash": "hash123",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.PRODUCTS, from_step=4)

        assert decision.next_step == 4
        assert decision.maybe_run_step3 is False
        assert decision.updated_caller_step is None  # No detour for products
        assert decision.skip_reason == "products_only"
        assert decision.needs_reeval is True  # Still need to rebuild offer

    def test_commercial_change_routes_to_step5(self):
        """COMMERCIAL change → Step 5 (Negotiation)."""
        event_state = {
            "current_step": 5,
            "caller_step": None,
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.COMMERCIAL, from_step=5)

        assert decision.next_step == 5
        assert decision.maybe_run_step3 is False
        assert decision.needs_reeval is True

    def test_deposit_change_routes_to_step7(self):
        """DEPOSIT change → Step 7 (Confirmation)."""
        event_state = {
            "current_step": 7,
            "caller_step": None,
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.DEPOSIT, from_step=7)

        assert decision.next_step == 7
        assert decision.maybe_run_step3 is False
        assert decision.needs_reeval is True

    def test_preserves_existing_caller_step(self):
        """If caller_step is already set, preserve it."""
        event_state = {
            "current_step": 3,
            "caller_step": 5,  # Already set from a previous detour
            "requirements_hash": "hash_new",
            "room_eval_hash": "hash_old",
        }

        decision = route_change_on_updated_variable(event_state, ChangeType.REQUIREMENTS)

        # Should preserve the existing caller_step=5
        assert decision.updated_caller_step == 5


@pytest.mark.v4
class TestDetectChangeType:
    """Test automatic change type detection from user_info and message."""

    def test_detects_date_change_when_date_confirmed(self):
        """Detect DATE change when date is already confirmed and user provides new date."""
        event_state = {
            "current_step": 4,
            "date_confirmed": True,
            "chosen_date": "2026-03-10",
        }
        user_info = {
            "date": "2026-03-17",
        }
        # Change detection requires message_text for intent pattern matching
        message_text = "Can we change the date to 17.03.2026 instead?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.DATE

    def test_no_date_change_when_not_confirmed_yet(self):
        """No DATE change if date isn't confirmed yet (normal flow)."""
        event_state = {
            "current_step": 2,
            "date_confirmed": False,
            "chosen_date": None,
        }
        user_info = {
            "date": "2026-03-17",
        }

        change_type = detect_change_type(event_state, user_info)

        assert change_type is None  # Normal flow, not a "change"

    def test_detects_room_change(self):
        """Detect ROOM change when user requests different room."""
        event_state = {
            "current_step": 4,
            "locked_room_id": "RoomA",
        }
        user_info = {
            "room": "RoomB",
        }
        # Change detection requires message_text for intent pattern matching
        message_text = "Can we switch to RoomB instead?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.ROOM

    def test_detects_requirements_change(self):
        """Detect REQUIREMENTS change when participants/layout changes."""
        event_state = {
            "current_step": 4,
            "locked_room_id": "RoomA",
            "requirements": {"number_of_participants": 20},  # Original value
        }
        user_info = {
            "participants": 36,  # Changed from original
        }
        # Change detection requires message_text for intent pattern matching
        message_text = "Actually, we're 36 people now instead of 20."

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.REQUIREMENTS

    def test_detects_products_change(self):
        """Detect PRODUCTS change in Step 4+."""
        event_state = {
            "current_step": 4,
            "locked_room_id": "RoomA",
        }
        # Use products_add for explicit add signal (strong signal path)
        user_info = {
            "products_add": ["Prosecco", "Coffee"],
        }
        # Change detection can also use message_text, but products_add is a direct signal
        message_text = "Could you include Prosecco and Coffee with the catering?"

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.PRODUCTS

    def test_detects_commercial_from_message_text(self):
        """Detect COMMERCIAL from price negotiation keywords."""
        event_state = {
            "current_step": 5,
        }
        user_info = {}
        message_text = "Can we get a discount on the price? Our budget is tight."

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.COMMERCIAL

    def test_detects_deposit_from_message_text(self):
        """Detect DEPOSIT from reservation keywords."""
        event_state = {
            "current_step": 7,
        }
        user_info = {}
        message_text = "We would like to make the deposit payment now."

        change_type = detect_change_type(event_state, user_info, message_text=message_text)

        assert change_type == ChangeType.DEPOSIT


@pytest.mark.v4
class TestOfferHashComputation:
    """Test offer hash computation for detecting offer changes."""

    def test_compute_offer_hash(self):
        """Compute stable hash for offer."""
        offer1 = {
            "products": ["Standard Buffet", "Wine Pairing"],
            "total": 1500.00,
            "subtotal": 1250.00,
            "tax": 250.00,
            "pricing": {"per_person": 50.00},
        }

        hash1 = compute_offer_hash(offer1)

        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA256 hex digest

    def test_offer_hash_changes_when_products_change(self):
        """Offer hash changes when products change."""
        offer1 = {
            "products": ["Standard Buffet"],
            "total": 1000.00,
        }
        offer2 = {
            "products": ["Standard Buffet", "Prosecco"],
            "total": 1200.00,
        }

        hash1 = compute_offer_hash(offer1)
        hash2 = compute_offer_hash(offer2)

        assert hash1 != hash2

    def test_offer_hash_same_for_identical_offers(self):
        """Offer hash is deterministic for identical offers."""
        offer1 = {
            "products": ["Standard Buffet", "Wine"],
            "total": 1500.00,
            "subtotal": 1250.00,
        }
        offer2 = {
            "products": ["Standard Buffet", "Wine"],
            "total": 1500.00,
            "subtotal": 1250.00,
        }

        hash1 = compute_offer_hash(offer1)
        hash2 = compute_offer_hash(offer2)

        assert hash1 == hash2
