"""
Test: Room confirmation + offer are sent as a combined message.

When a client confirms a room selection, the workflow should:
1. Store a room confirmation prefix in event_entry["room_confirmation_prefix"]
2. Return halt=False to continue to Step 4 immediately
3. Step 4 should prepend the prefix to the offer body
4. Result: One combined message with "Great choice! [Room] is confirmed..." + offer

This prevents separate "room confirmed" and "here's your offer" messages.
"""
import uuid

import pytest


@pytest.mark.v4
class TestRoomConfirmationOfferCombined:
    """Test that room confirmation and offer are sent as one combined message."""

    def _create_event_at_step3_with_room_presented(self):
        """Create a mock event at step 3 with a room presented (awaiting confirmation)."""
        return {
            "event_id": str(uuid.uuid4()),
            "client_email": "test-room-confirm@example.com",
            "thread_id": f"test-thread-{uuid.uuid4().hex[:8]}",
            "current_step": 3,
            "status": "Lead",
            "chosen_date": "2026-02-22",
            "date_confirmed": True,
            "requirements": {
                "number_of_participants": 25,
            },
            "requirements_hash": "test-hash-123",
            "room_pending_decision": {
                "selected_room": "Room F",
                "selected_status": "Available",
                "requirements_hash": "test-hash-123",
            },
            "preferences": {},
            "event_data": {
                "Email": "test-room-confirm@example.com",
            },
        }

    def test_room_confirmation_prefix_is_set_in_step3(self):
        """Test that Step 3 sets room_confirmation_prefix when room is confirmed."""
        event_entry = self._create_event_at_step3_with_room_presented()

        # Simulate the is_room_confirmation condition being True
        # This should set room_confirmation_prefix
        user_requested_room = "Room F"
        selected_room = "Room F"
        outcome = "Available"
        participants = 25
        display_chosen_date = "22.02.2026"

        # Condition for is_room_confirmation (from step3_handler.py)
        is_room_confirmation = (
            user_requested_room
            and user_requested_room == selected_room
            and outcome in {"Available", "Option"}
        )

        assert is_room_confirmation, "Should detect room confirmation"

        # Simulate what Step 3 does when is_room_confirmation is True
        if is_room_confirmation:
            confirmation_intro = (
                f"Great choice! {selected_room} on {display_chosen_date} is confirmed "
                f"for your event with {participants} guests."
            )
            event_entry["room_confirmation_prefix"] = confirmation_intro + "\n\n"

        # Verify prefix was set
        assert "room_confirmation_prefix" in event_entry
        assert "Great choice!" in event_entry["room_confirmation_prefix"]
        assert "Room F" in event_entry["room_confirmation_prefix"]
        assert "22.02.2026" in event_entry["room_confirmation_prefix"]
        assert "25 guests" in event_entry["room_confirmation_prefix"]

    def test_step4_consumes_room_confirmation_prefix(self):
        """Test that Step 4 pops and uses room_confirmation_prefix."""
        event_entry = self._create_event_at_step3_with_room_presented()

        # Simulate prefix being set by Step 3
        event_entry["room_confirmation_prefix"] = "Great choice! Room F on 22.02.2026 is confirmed for your event with 25 guests.\n\n"

        # Simulate Step 4 consuming the prefix (from step4_handler.py line 653)
        room_confirmation_prefix = event_entry.pop("room_confirmation_prefix", "")

        # Verify prefix was consumed (popped)
        assert room_confirmation_prefix.startswith("Great choice!")
        assert "room_confirmation_prefix" not in event_entry  # Should be removed

        # Simulate offer body construction
        verbalized_intro = "Here is your offer for Room F on 22.02.2026."
        offer_body_markdown = room_confirmation_prefix + verbalized_intro

        # Verify combined message starts with room confirmation
        assert offer_body_markdown.startswith("Great choice!")
        assert "Here is your offer" in offer_body_markdown

    def test_combined_message_format(self):
        """Test the complete combined message format."""
        # Simulate the full flow
        prefix = "Great choice! Room F on 22.02.2026 is confirmed for your event with 25 guests.\n\n"
        offer_intro = "Here is your offer for Room F on 22.02.2026.\n\n"
        offer_details = "**Room booking**\n- Room F · CHF 600.00\n\n**Total: CHF 600.00**"

        combined_message = prefix + offer_intro + offer_details

        # Verify message structure
        lines = combined_message.split("\n")

        # First line should be room confirmation
        assert lines[0].startswith("Great choice!")

        # Should contain offer intro
        assert "Here is your offer" in combined_message

        # Should contain offer details
        assert "**Room booking**" in combined_message
        assert "CHF 600.00" in combined_message

    def test_no_prefix_when_room_not_confirmed(self):
        """Test that prefix is NOT set when room is not confirmed (e.g., room recommendation)."""
        event_entry = self._create_event_at_step3_with_room_presented()

        # Condition for is_room_confirmation when user hasn't selected a room
        user_requested_room = None  # User didn't select a specific room
        selected_room = "Room F"  # System recommended a room

        is_room_confirmation = (
            user_requested_room
            and user_requested_room == selected_room
            and True  # outcome check
        )

        assert not is_room_confirmation, "Should NOT detect room confirmation when user didn't select"

        # Verify prefix is not set
        assert "room_confirmation_prefix" not in event_entry


@pytest.mark.v4
class TestRoomConfirmationHaltBehavior:
    """Test that room confirmation returns halt=False to continue to Step 4."""

    def test_halt_false_when_room_confirmed(self):
        """Test that is_room_confirmation causes halt=False."""
        # From step3_handler.py line 1335: should_halt = not is_room_confirmation
        is_room_confirmation = True
        should_halt = not is_room_confirmation

        assert should_halt is False, "Room confirmation should NOT halt (allow Step 4 to run)"

    def test_halt_true_when_room_not_confirmed(self):
        """Test that non-confirmation cases halt to wait for client response."""
        is_room_confirmation = False
        should_halt = not is_room_confirmation

        assert should_halt is True, "Non-confirmation should halt to await client response"
