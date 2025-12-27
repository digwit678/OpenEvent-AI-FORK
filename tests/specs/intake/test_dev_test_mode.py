"""
Characterization tests for dev_test_mode helper (I2 refactoring).

These tests lock down the behavior of the DEV_TEST_MODE flow
that offers users a "continue or reset" choice when there's an
existing event at step > 1.
"""

import os
import pytest
from unittest.mock import patch

from backend.workflows.steps.step1_intake.trigger.dev_test_mode import (
    is_dev_test_mode_enabled,
    should_show_dev_choice,
    build_dev_choice_result,
    maybe_show_dev_choice,
)


class TestIsDevTestModeEnabled:
    """Tests for is_dev_test_mode_enabled()."""

    def test_disabled_by_default(self):
        """When DEV_TEST_MODE is not set, returns False."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove DEV_TEST_MODE if it exists
            os.environ.pop("DEV_TEST_MODE", None)
            assert is_dev_test_mode_enabled() is False

    def test_enabled_with_1(self):
        """DEV_TEST_MODE=1 enables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert is_dev_test_mode_enabled() is True

    def test_enabled_with_true(self):
        """DEV_TEST_MODE=true enables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "true"}):
            assert is_dev_test_mode_enabled() is True

    def test_enabled_with_TRUE(self):
        """DEV_TEST_MODE=TRUE (uppercase) enables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "TRUE"}):
            assert is_dev_test_mode_enabled() is True

    def test_enabled_with_yes(self):
        """DEV_TEST_MODE=yes enables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "yes"}):
            assert is_dev_test_mode_enabled() is True

    def test_disabled_with_false(self):
        """DEV_TEST_MODE=false disables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "false"}):
            assert is_dev_test_mode_enabled() is False

    def test_disabled_with_0(self):
        """DEV_TEST_MODE=0 disables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "0"}):
            assert is_dev_test_mode_enabled() is False

    def test_disabled_with_random_value(self):
        """DEV_TEST_MODE=random disables dev mode."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "random"}):
            assert is_dev_test_mode_enabled() is False


class TestShouldShowDevChoice:
    """Tests for should_show_dev_choice()."""

    @pytest.fixture
    def linked_event(self):
        """Sample linked event at step 3."""
        return {
            "event_id": "evt-123",
            "current_step": 3,
            "chosen_date": "2026-02-14",
            "locked_room_id": "room-a",
        }

    def test_returns_false_when_dev_mode_disabled(self, linked_event):
        """No dev choice when DEV_TEST_MODE is off."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "0"}):
            assert should_show_dev_choice(linked_event, 3, False) is False

    def test_returns_false_when_no_linked_event(self):
        """No dev choice when there's no linked event."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(None, 1, False) is False

    def test_returns_false_when_step_1(self, linked_event):
        """No dev choice for step 1 (initial intake)."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(linked_event, 1, False) is False

    def test_returns_false_when_skip_flag_set(self, linked_event):
        """No dev choice when skip_dev_choice=True."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(linked_event, 3, True) is False

    def test_returns_true_when_all_conditions_met(self, linked_event):
        """Shows dev choice when all conditions are met."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(linked_event, 3, False) is True

    def test_returns_true_for_step_2(self, linked_event):
        """Shows dev choice for step 2."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(linked_event, 2, False) is True

    def test_returns_true_for_step_5(self, linked_event):
        """Shows dev choice for step 5."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            assert should_show_dev_choice(linked_event, 5, False) is True


class TestBuildDevChoiceResult:
    """Tests for build_dev_choice_result()."""

    @pytest.fixture
    def linked_event(self):
        """Sample linked event."""
        return {
            "event_id": "evt-456",
            "chosen_date": "2026-03-15",
            "locked_room_id": "room-b",
            "offer_accepted": True,
            "event_data": {"Event Date": "2026-03-15"},
        }

    def test_returns_group_result_with_correct_action(self, linked_event):
        """Result has action='dev_choice_required'."""
        result = build_dev_choice_result(linked_event, 4, "Step4_Offer", "test@example.com")
        assert result.action == "dev_choice_required"

    def test_returns_group_result_with_halt_true(self, linked_event):
        """Result has halt=True."""
        result = build_dev_choice_result(linked_event, 4, "Step4_Offer", "test@example.com")
        assert result.halt is True

    def test_payload_contains_event_info(self, linked_event):
        """Payload contains event details."""
        result = build_dev_choice_result(linked_event, 4, "Step4_Offer", "test@example.com")
        payload = result.payload

        assert payload["client_id"] == "test@example.com"
        assert payload["event_id"] == "evt-456"
        assert payload["current_step"] == 4
        assert payload["step_name"] == "Step4_Offer"
        assert payload["event_date"] == "2026-03-15"
        assert payload["locked_room"] == "room-b"
        assert payload["offer_accepted"] is True

    def test_payload_contains_options(self, linked_event):
        """Payload contains continue/reset options."""
        result = build_dev_choice_result(linked_event, 4, "Step4_Offer", "test@example.com")
        options = result.payload["options"]

        assert len(options) == 2
        assert options[0]["id"] == "continue"
        assert "Step4_Offer" in options[0]["label"]
        assert options[1]["id"] == "reset"
        assert "Reset" in options[1]["label"]

    def test_payload_message_contains_details(self, linked_event):
        """Payload message contains event details."""
        result = build_dev_choice_result(linked_event, 4, "Step4_Offer", "test@example.com")
        message = result.payload["message"]

        assert "test@example.com" in message
        assert "Step4_Offer" in message

    def test_handles_missing_chosen_date(self):
        """Falls back to event_data.Event Date when chosen_date missing."""
        event = {
            "event_id": "evt-789",
            "event_data": {"Event Date": "2026-04-20"},
            "locked_room_id": None,
        }
        result = build_dev_choice_result(event, 2, "Step2_Date", "user@test.com")
        assert result.payload["event_date"] == "2026-04-20"

    def test_handles_missing_room(self):
        """Shows 'none' when locked_room_id is missing."""
        event = {
            "event_id": "evt-999",
            "chosen_date": "2026-05-10",
            "locked_room_id": None,
        }
        result = build_dev_choice_result(event, 2, "Step2_Date", "user@test.com")
        assert result.payload["locked_room"] == "none"


class TestMaybeShowDevChoice:
    """Integration tests for maybe_show_dev_choice()."""

    @pytest.fixture
    def linked_event(self):
        """Sample linked event."""
        return {
            "event_id": "evt-integration",
            "chosen_date": "2026-06-01",
            "locked_room_id": "room-c",
            "offer_accepted": False,
        }

    def test_returns_none_when_dev_mode_disabled(self, linked_event):
        """Returns None when DEV_TEST_MODE is off."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "0"}):
            result = maybe_show_dev_choice(
                linked_event, 3, "Step3_Room", "test@example.com", False
            )
            assert result is None

    def test_returns_none_when_step_1(self, linked_event):
        """Returns None for step 1."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            result = maybe_show_dev_choice(
                linked_event, 1, "Step1_Intake", "test@example.com", False
            )
            assert result is None

    def test_returns_group_result_when_conditions_met(self, linked_event):
        """Returns GroupResult when all conditions are met."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            result = maybe_show_dev_choice(
                linked_event, 3, "Step3_Room", "test@example.com", False
            )
            assert result is not None
            assert result.action == "dev_choice_required"
            assert result.halt is True
            assert result.payload["event_id"] == "evt-integration"

    def test_returns_none_when_skip_flag_set(self, linked_event):
        """Returns None when skip_dev_choice=True."""
        with patch.dict(os.environ, {"DEV_TEST_MODE": "1"}):
            result = maybe_show_dev_choice(
                linked_event, 3, "Step3_Room", "test@example.com", True
            )
            assert result is None
