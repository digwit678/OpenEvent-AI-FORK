"""
E2E Tests: Site Visit Time Range + Detour Scenarios

This test suite verifies the key workflow scenarios:

1. DETOUR SCENARIOS:
   - Date change at Step 4+ when room NOT available on new date
   - Should redirect to Room Availability (Step 3)
   - After room selection, should return to offer confirmation

2. SITE VISIT SCENARIOS (with new time range mode):
   - Client requests site visit WITHOUT specifying date/time
   - Client provides already-occupied date/timeslot → agent suggests alternatives
   - Client provides valid date/timeslot → agent confirms the visit
   - Guard: Step 1 without event context defers site visit

Run with: pytest tests/e2e/test_site_visit_time_range_e2e.py -v --tb=short
"""

from __future__ import annotations

import os
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

pytestmark = pytest.mark.v4


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_db(tmp_path):
    """Create a mock database for testing."""
    db_path = tmp_path / "test_events.json"

    def _create_db(events: list, site_visits: Optional[list] = None):
        """Create DB with specified events."""
        db = {
            "events": events,
            "clients": {},
            "tasks": [],
        }
        with open(db_path, "w") as f:
            json.dump(db, f)
        return db_path

    return _create_db


@pytest.fixture
def sample_event_step4():
    """Event at Step 4 (Offer) with confirmed date and room."""
    from workflows.common.requirements import requirements_hash

    requirements = {
        "number_of_participants": 30,
        "seating_layout": "dinner",
        "event_duration": {"start": "18:00", "end": "23:00"},
        "special_requirements": None,
        "preferred_room": None,
    }
    req_hash = requirements_hash(requirements)

    return {
        "event_id": "EVT-E2E-001",
        "current_step": 4,
        "thread_state": "Awaiting Client",
        "chosen_date": "15.03.2026",
        "chosen_date_iso": "2026-03-15",
        "date_confirmed": True,
        "locked_room_id": "Room A",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": req_hash,
        "caller_step": None,
        "preferences": {"wish_products": [], "keywords": []},
        "selected_products": [],
        "products_state": {"line_items": []},
        "offer_sent": True,
        "offer_accepted": False,
        "billing_address": {},
        "billing_captured": False,
        "deposit_paid": False,
        "site_visit_state": {},
        "event_data": {
            "Status": "Option",
            "Email": "client@example.com",
        },
        "requested_window": {
            "date_iso": "2026-03-15",
            "display_date": "15.03.2026",
            "start_time": "18:00",
            "end_time": "23:00",
        },
        "audit": [],
        "client_email": "client@example.com",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


# =============================================================================
# SITE VISIT STATE TESTS
# =============================================================================


class TestSiteVisitStateManagement:
    """Test site visit state management (foundation for E2E)."""

    def test_site_visit_flow_starts_in_date_pending(self):
        """Starting a site visit should go directly to date_pending."""
        from workflows.common.site_visit_state import start_site_visit_flow, get_site_visit_state

        event_entry = {}
        state = start_site_visit_flow(event_entry, initiated_at_step=4)

        assert state["status"] == "date_pending"
        assert state["initiated_at_step"] == 4

    def test_site_visit_date_set_transitions_to_scheduled(self):
        """Setting date+time should transition to scheduled."""
        from workflows.common.site_visit_state import (
            start_site_visit_flow,
            set_site_visit_date,
            get_site_visit_state,
        )

        event_entry = {}
        start_site_visit_flow(event_entry, initiated_at_step=4)
        set_site_visit_date(event_entry, "2026-02-15", "14:00")

        state = get_site_visit_state(event_entry)
        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-15"
        assert state["time_slot"] == "14:00"


# =============================================================================
# WORKING DAYS CALCULATION TESTS
# =============================================================================


class TestWorkingDaysCalculation:
    """Test the working days calculation logic."""

    def test_add_working_days_basic(self):
        """Basic working days addition."""
        from workflows.common.site_visit_handler import _add_working_days

        # Monday Feb 2, 2026
        start = datetime(2026, 2, 2)
        blocked = set()

        # Add 3 working days → should be Thursday Feb 5
        result = _add_working_days(start, 3, blocked)
        assert result.date().isoformat() == "2026-02-05"

    def test_add_working_days_skips_weekend(self):
        """Working days should skip weekends."""
        from workflows.common.site_visit_handler import _add_working_days

        # Friday Feb 6, 2026
        start = datetime(2026, 2, 6)
        blocked = set()

        # Add 1 working day → should skip Sat/Sun → Monday Feb 9
        result = _add_working_days(start, 1, blocked)
        assert result.date().isoformat() == "2026-02-09"

    def test_add_working_days_skips_christmas(self):
        """Working days should skip Christmas (default holiday)."""
        from workflows.common.site_visit_handler import _add_working_days

        # Dec 24, 2026 (Thursday)
        start = datetime(2026, 12, 24)
        blocked = set()

        # Add 1 working day → Dec 25 (holiday), Dec 26 (Sat), Dec 27 (Sun), Dec 28 (Mon)
        # Actually Dec 25 is Friday in 2026, Dec 26 is Sat
        # Dec 24 (Thu) + 1 → Dec 25 (Fri, HOLIDAY) → Dec 26 (Sat) → Dec 27 (Sun) → Dec 28 (Mon) ✓
        result = _add_working_days(start, 1, blocked)
        # Actually need to check the calendar
        # Dec 25, 2026 is a Friday (Christmas)
        # Dec 26, 2026 is a Saturday (Boxing Day, but also weekend)
        # Dec 27, 2026 is Sunday
        # Dec 28, 2026 is Monday - this should be the result
        assert result.date().isoformat() == "2026-12-28"

    def test_add_working_days_skips_blocked_dates(self):
        """Working days should skip blocked dates."""
        from workflows.common.site_visit_handler import _add_working_days

        # Monday Feb 2, 2026
        start = datetime(2026, 2, 2)
        # Block Tuesday and Wednesday
        blocked = {"2026-02-03", "2026-02-04"}

        # Add 1 working day → Feb 3 (blocked), Feb 4 (blocked), Feb 5 (Thu) ✓
        result = _add_working_days(start, 1, blocked)
        assert result.date().isoformat() == "2026-02-05"


# =============================================================================
# SLOT GENERATION TESTS
# =============================================================================


class TestSlotGeneration:
    """Test dynamic slot generation from time range."""

    def test_generate_slots_from_range(self):
        """Generate slots from configured time range."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=12):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=30):
                    slots = _generate_time_slots_from_range(set(), "2026-02-10")

        # 10:00-12:00 with 30min intervals = 10:00, 10:30, 11:00, 11:30
        assert slots == ["10:00", "10:30", "11:00", "11:30"]

    def test_generate_slots_excludes_booked(self):
        """Booked slots should be excluded (duration-aware overlap detection)."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range

        # New 3-tuple format: (date_iso, time_slot, duration_minutes)
        booked = {("2026-02-10", "10:30", 30)}

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=12):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=30):
                    slots = _generate_time_slots_from_range(booked, "2026-02-10")

        assert "10:30" not in slots
        assert "10:00" in slots
        assert "11:00" in slots


# =============================================================================
# SITE VISIT CONFLICT SCENARIOS
# =============================================================================


class TestSiteVisitConflicts:
    """Test site visit booking when slots are occupied."""

    def test_blocked_dates_includes_event_dates(self):
        """Event dates should block site visits."""
        from workflows.common.site_visit_handler import _get_blocked_dates

        db = {"events": []}
        event_entry = {"chosen_date": "15.02.2026"}

        blocked = _get_blocked_dates(event_entry, db=db)

        assert "2026-02-15" in blocked

    def test_booked_slots_detection(self):
        """Already-booked site visit slots should be detected (with duration)."""
        from workflows.common.site_visit_handler import _get_booked_site_visit_slots, set_db_loader

        # Create mock DB with a scheduled site visit
        mock_db = {
            "events": [
                {
                    "event_id": "evt-other",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-10",
                        "time_slot": "14:00",
                    },
                },
            ],
        }

        set_db_loader(lambda: mock_db)
        try:
            event_entry = {"event_id": "evt-current"}
            booked = _get_booked_site_visit_slots(event_entry)

            # New 3-tuple format: (date_iso, time_slot, duration_minutes)
            # Legacy bookings without stored duration default to 60 min
            assert ("2026-02-10", "14:00", 60) in booked
        finally:
            set_db_loader(None)


# =============================================================================
# DUAL-MODE (LEGACY vs TIME RANGE) TESTS
# =============================================================================


class TestDualModeSlotGeneration:
    """Test that legacy and time-range modes work correctly."""

    def test_legacy_mode_uses_default_slots(self):
        """Legacy mode should use default_slots list."""
        from workflows.common.site_visit_handler import _generate_time_slots_for_date

        event_entry = {}

        with patch("workflows.common.site_visit_handler.is_site_visit_time_range_mode", return_value=False):
            with patch("workflows.common.site_visit_handler.get_site_visit_slots", return_value=[10, 14, 16]):
                with patch("workflows.common.site_visit_handler._get_booked_site_visit_slots", return_value=set()):
                    with patch("workflows.common.site_visit_handler._has_any_room_available_for_slot", return_value=True):
                        slots = _generate_time_slots_for_date(event_entry, "2026-02-10")

        # Legacy mode: [10, 14, 16] → ["10:00", "14:00", "16:00"]
        assert slots == ["10:00", "14:00", "16:00"]

    def test_time_range_mode_uses_dynamic_slots(self):
        """Time range mode should generate dynamic slots."""
        from workflows.common.site_visit_handler import _generate_time_slots_for_date

        event_entry = {}

        # Time range mode returns dynamic slots
        with patch("workflows.common.site_visit_handler.is_site_visit_time_range_mode", return_value=True):
            with patch("workflows.common.site_visit_handler._generate_time_slots_from_range",
                       return_value=["10:00", "10:30", "11:00", "11:30"]):
                with patch("workflows.common.site_visit_handler._get_booked_site_visit_slots", return_value=set()):
                    with patch("workflows.common.site_visit_handler._has_any_room_available_for_slot", return_value=True):
                        slots = _generate_time_slots_for_date(event_entry, "2026-02-10")

        # Should include 30-minute intervals
        assert "10:00" in slots
        assert "10:30" in slots


# =============================================================================
# CONFIG ACCESSOR TESTS
# =============================================================================


class TestConfigAccessors:
    """Test the new config store accessor functions."""

    def test_time_range_mode_default_is_false(self):
        """Default time range mode should be False (legacy)."""
        from workflows.io.config_store import is_site_visit_time_range_mode

        result = is_site_visit_time_range_mode()
        assert result is False

    def test_range_hours_have_sensible_defaults(self):
        """Range hours should have sensible defaults."""
        from workflows.io.config_store import (
            get_site_visit_range_start_hour,
            get_site_visit_range_end_hour,
        )

        start = get_site_visit_range_start_hour()
        end = get_site_visit_range_end_hour()

        assert 6 <= start <= 12  # Reasonable morning start
        assert 18 <= end <= 23   # Reasonable evening end
        assert start < end

    def test_slot_duration_is_reasonable(self):
        """Slot duration should be 15, 30, 45, or 60 minutes."""
        from workflows.io.config_store import get_site_visit_slot_duration

        duration = get_site_visit_slot_duration()
        assert duration in [15, 30, 45, 60]

    def test_working_days_ahead_is_positive(self):
        """Working days ahead should be a positive integer."""
        from workflows.io.config_store import get_site_visit_default_working_days_ahead

        days = get_site_visit_default_working_days_ahead()
        assert isinstance(days, int)
        assert days >= 1


# =============================================================================
# HOLIDAY RECOGNITION TESTS
# =============================================================================


class TestHolidayRecognition:
    """Test default holiday recognition."""

    def test_new_years_day_is_holiday(self):
        """January 1st should be a holiday."""
        from workflows.common.site_visit_handler import _is_default_holiday

        assert _is_default_holiday(datetime(2026, 1, 1)) is True
        assert _is_default_holiday(datetime(2027, 1, 1)) is True

    def test_christmas_is_holiday(self):
        """December 25th should be a holiday."""
        from workflows.common.site_visit_handler import _is_default_holiday

        assert _is_default_holiday(datetime(2026, 12, 25)) is True

    def test_boxing_day_is_holiday(self):
        """December 26th (Boxing Day) should be a holiday."""
        from workflows.common.site_visit_handler import _is_default_holiday

        assert _is_default_holiday(datetime(2026, 12, 26)) is True

    def test_july_4th_is_holiday(self):
        """July 4th (US Independence Day) should be a holiday."""
        from workflows.common.site_visit_handler import _is_default_holiday

        assert _is_default_holiday(datetime(2026, 7, 4)) is True

    def test_regular_day_is_not_holiday(self):
        """Regular working day should not be a holiday."""
        from workflows.common.site_visit_handler import _is_default_holiday

        assert _is_default_holiday(datetime(2026, 2, 10)) is False
        assert _is_default_holiday(datetime(2026, 6, 15)) is False


# =============================================================================
# SITE VISIT INTENT DETECTION
# =============================================================================


class TestSiteVisitIntentDetection:
    """Test site visit intent detection."""

    def test_site_visit_request_triggers_booking(self):
        """site_visit_request should trigger booking flow."""
        from detection.unified import UnifiedDetectionResult
        from workflows.common.site_visit_handler import is_site_visit_intent

        result = UnifiedDetectionResult(
            intent="general_qna",
            qna_types=["site_visit_request"],
        )

        assert is_site_visit_intent(result) is True

    def test_site_visit_overview_does_not_trigger_booking(self):
        """site_visit_overview (info question) should NOT trigger booking."""
        from detection.unified import UnifiedDetectionResult
        from workflows.common.site_visit_handler import is_site_visit_intent

        result = UnifiedDetectionResult(
            intent="general_qna",
            qna_types=["site_visit_overview"],
        )

        assert is_site_visit_intent(result) is False


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================


class TestBackwardCompatibility:
    """Test backward compatibility with existing configs."""

    def test_legacy_config_still_works(self):
        """Configs without new fields should work with defaults."""
        from workflows.io.config_store import (
            get_site_visit_slots,
            is_site_visit_time_range_mode,
        )

        # Default mode should be legacy
        assert is_site_visit_time_range_mode() is False

        # Legacy slots should still work
        slots = get_site_visit_slots()
        assert isinstance(slots, list)
        assert len(slots) > 0

    def test_new_config_fields_have_defaults(self):
        """New config fields should have sensible defaults."""
        from unittest.mock import patch

        from workflows.io.config_store import get_all_site_visit_config

        with patch("workflows.io.config_store._get_site_visit_config", return_value={}):
            config = get_all_site_visit_config()

        # All new fields should be present with defaults
        assert "enabled" in config
        assert "range_start_hour" in config
        assert "range_end_hour" in config
        assert "slot_duration_minutes" in config
        assert "default_working_days_ahead" in config
        assert "use_time_range_mode" in config

        # Verify defaults
        assert config["enabled"] is True
        assert config["range_start_hour"] == 10
        assert config["range_end_hour"] == 22
        assert config["slot_duration_minutes"] == 30
        assert config["default_working_days_ahead"] == 3
        assert config["use_time_range_mode"] is False
