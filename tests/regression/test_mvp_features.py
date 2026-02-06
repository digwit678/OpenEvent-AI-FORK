"""Tests for MVP features: On-Demand Site Visit and Mandatory Time Slot Booking.

Phase 1: On-Demand Site Visit
- Site visits can be requested at any step (2-7)
- Step 1 deferred until event context exists

Phase 2: Mandatory Time Slot Booking
- Optional time slot selection (Morning/Afternoon/Evening)
- Disabled by default (require_selection=False)
- Uses LLM detection for slot parsing
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import time

pytestmark = pytest.mark.v4


# =============================================================================
# Phase 1: On-Demand Site Visit Tests
# =============================================================================

class TestSiteVisitAllowed:
    """Test site_visit_allowed() no longer requires locked_room_id."""

    def test_site_visit_allowed_without_locked_room(self):
        """Site visit should be allowed even without locked_room_id."""
        from workflows.common.room_rules import site_visit_allowed

        event_entry = {
            "policy": {"allow_site_visit": True},
            # No locked_room_id
        }
        assert site_visit_allowed(event_entry) is True

    def test_site_visit_allowed_with_policy_disabled(self):
        """Site visit should be blocked when policy disables it."""
        from workflows.common.room_rules import site_visit_allowed

        event_entry = {
            "policy": {"allow_site_visit": False},
        }
        assert site_visit_allowed(event_entry) is False

    def test_site_visit_allowed_default_policy(self):
        """Site visit should be allowed by default (no policy set)."""
        from workflows.common.room_rules import site_visit_allowed

        event_entry = {}
        assert site_visit_allowed(event_entry) is True

    def test_site_visit_allowed_disabled_by_config(self):
        """Site visit should be blocked when config disables it."""
        from workflows.common.room_rules import site_visit_allowed

        event_entry = {"policy": {"allow_site_visit": True}}

        with patch("workflows.io.config_store._get_site_visit_config", return_value={"enabled": False}):
            assert site_visit_allowed(event_entry) is False


class TestSiteVisitStep1Guard:
    """Test Step 1 guard for site visit requests."""

    def test_site_visit_deferred_at_step_1_without_context(self):
        """Site visit at Step 1 without event context should be deferred."""
        from workflows.common.site_visit_handler import _start_site_visit
        from workflows.common.types import WorkflowState
        from pathlib import Path

        # Create minimal state and event_entry at Step 1
        state = WorkflowState(
            client_id="test@example.com",
            thread_id="test-thread",
            message=MagicMock(body="Can I schedule a tour?"),
            db_path=Path("/tmp/test.json"),
            db={},
        )
        state.extras = {}

        event_entry = {
            "current_step": 1,
            # No event_date, no participants
        }

        result = _start_site_visit(state, event_entry, detection=None)

        assert result.action == "site_visit_deferred"
        assert result.halt is True
        assert len(state.draft_messages) > 0
        assert "site_visit_needs_context" in state.draft_messages[0].get("topic", "")

    def test_site_visit_proceeds_at_step_1_with_date(self):
        """Site visit at Step 1 with event date should proceed."""
        from workflows.common.site_visit_handler import _start_site_visit
        from workflows.common.types import WorkflowState
        from pathlib import Path

        state = WorkflowState(
            client_id="test@example.com",
            thread_id="test-thread",
            message=MagicMock(body="Can I schedule a tour?"),
            db_path=Path("/tmp/test.json"),
            db={},
        )
        state.extras = {}

        event_entry = {
            "current_step": 1,
            "chosen_date": "2026-05-15",  # Has event date
        }

        # This will try to offer dates, which may fail without DB
        # Just verify it doesn't return "deferred"
        with patch("workflows.common.site_visit_handler._load_database", return_value={"events": []}):
            result = _start_site_visit(state, event_entry, detection=None)

        assert result.action != "site_visit_deferred"


# =============================================================================
# Phase 2: Mandatory Time Slot Booking Tests
# =============================================================================

class TestTimeSlotConfig:
    """Test event time slot configuration."""

    def test_default_time_slots(self):
        """Default slots should be Morning/Afternoon/Evening."""
        from workflows.io.config_store import get_event_time_slots

        slots = get_event_time_slots()

        assert len(slots) == 3
        labels = [s["label"] for s in slots]
        assert "Morning" in labels
        assert "Afternoon" in labels
        assert "Evening" in labels

    def test_time_slot_required_default_false(self):
        """Time slot selection should be disabled by default."""
        from workflows.io.config_store import is_event_time_slot_required

        # Without any config override, should be False
        assert is_event_time_slot_required() is False


class TestTimeSlotFlow:
    """Test time_slot_flow module functions."""

    def test_should_prompt_time_slot_disabled(self):
        """Should not prompt when feature is disabled."""
        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            should_prompt_time_slot,
        )

        event_entry = {}
        # With default config (require_selection=False), should not prompt
        assert should_prompt_time_slot(event_entry, None, None) is False

    @patch("workflows.steps.step2_date_confirmation.trigger.time_slot_flow.is_event_time_slot_required")
    def test_should_prompt_time_slot_enabled(self, mock_required):
        """Should prompt when feature is enabled and no times provided."""
        mock_required.return_value = True

        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            should_prompt_time_slot,
        )

        event_entry = {}
        assert should_prompt_time_slot(event_entry, None, None) is True

    @patch("workflows.steps.step2_date_confirmation.trigger.time_slot_flow.is_event_time_slot_required")
    def test_should_not_prompt_when_times_provided(self, mock_required):
        """Should not prompt when specific times are already provided."""
        mock_required.return_value = True

        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            should_prompt_time_slot,
        )

        event_entry = {}
        # When both start and end time are provided
        assert should_prompt_time_slot(event_entry, "14:00", "18:00") is False

    @patch("workflows.steps.step2_date_confirmation.trigger.time_slot_flow.is_event_time_slot_required")
    def test_should_not_prompt_during_detour(self, mock_required):
        """Should not prompt when in a detour (caller_step set)."""
        mock_required.return_value = True

        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            should_prompt_time_slot,
        )

        event_entry = {"caller_step": 5}  # In detour from Step 5
        assert should_prompt_time_slot(event_entry, None, None) is False

    def test_parse_slot_from_detection_morning(self):
        """Should parse 'morning' label from detection."""
        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            parse_slot_from_detection,
        )
        from detection.unified import UnifiedDetectionResult

        detection = UnifiedDetectionResult(time_slot_label="morning")
        slots_config = [
            {"label": "Morning", "start": 9, "end": 12},
            {"label": "Afternoon", "start": 13, "end": 17},
            {"label": "Evening", "start": 18, "end": 22},
        ]

        result = parse_slot_from_detection(detection, slots_config)

        assert result is not None
        start, end = result
        assert start == "09:00"
        assert end == "12:00"

    def test_parse_slot_from_detection_ordinal(self):
        """Should parse ordinal ('first', 'second') from detection."""
        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            parse_slot_from_detection,
        )
        from detection.unified import UnifiedDetectionResult

        detection = UnifiedDetectionResult(time_slot_label="second")
        slots_config = [
            {"label": "Morning", "start": 9, "end": 12},
            {"label": "Afternoon", "start": 13, "end": 17},
            {"label": "Evening", "start": 18, "end": 22},
        ]

        result = parse_slot_from_detection(detection, slots_config)

        assert result is not None
        start, end = result
        # Second slot = Afternoon
        assert start == "13:00"
        assert end == "17:00"

    def test_parse_slot_from_detection_no_match(self):
        """Should return None when label doesn't match any slot."""
        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            parse_slot_from_detection,
        )
        from detection.unified import UnifiedDetectionResult

        detection = UnifiedDetectionResult(time_slot_label="midnight")
        slots_config = [
            {"label": "Morning", "start": 9, "end": 12},
        ]

        result = parse_slot_from_detection(detection, slots_config)
        assert result is None

    def test_set_and_get_pending_state(self):
        """Should correctly set and retrieve pending time slot state."""
        from workflows.steps.step2_date_confirmation.trigger.time_slot_flow import (
            set_time_slot_pending,
            get_pending_slot_info,
            is_time_slot_pending,
            clear_time_slot_pending,
        )

        event_entry = {}

        # Initially not pending
        assert is_time_slot_pending(event_entry) is False

        # Set pending
        set_time_slot_pending(event_entry, "2026-05-15", "May 15, 2026")

        # Now pending
        assert is_time_slot_pending(event_entry) is True

        # Get info
        info = get_pending_slot_info(event_entry)
        assert info is not None
        assert info["date_iso"] == "2026-05-15"
        assert info["date_display"] == "May 15, 2026"
        assert len(info["slots"]) == 3

        # Clear
        clear_time_slot_pending(event_entry)
        assert is_time_slot_pending(event_entry) is False


class TestTimeSlotLLMDetection:
    """Test time_slot_label in unified detection."""

    def test_time_slot_label_in_dataclass(self):
        """time_slot_label should be a field in UnifiedDetectionResult."""
        from detection.unified import UnifiedDetectionResult

        result = UnifiedDetectionResult(time_slot_label="afternoon")
        assert result.time_slot_label == "afternoon"

    def test_time_slot_label_in_to_dict(self):
        """time_slot_label should appear in to_dict() output."""
        from detection.unified import UnifiedDetectionResult

        result = UnifiedDetectionResult(time_slot_label="morning")
        d = result.to_dict()

        assert "time_slot_label" in d.get("entities", {})
        assert d["entities"]["time_slot_label"] == "morning"
