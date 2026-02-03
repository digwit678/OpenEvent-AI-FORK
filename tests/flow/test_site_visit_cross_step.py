"""Tests for cross-step site visit booking.

Site visits can be initiated at ANY workflow step (2-7).

IMPORTANT: Site visits are VENUE-WIDE (not room-specific).
- No room selection needed
- Conflict with events: site visits CANNOT be booked on event days
"""
import pytest

pytestmark = pytest.mark.v4

from workflows.common.site_visit_state import (
    SiteVisitState,
    cancel_site_visit,
    complete_site_visit,
    get_site_visit_state,
    is_site_visit_active,
    is_site_visit_scheduled,
    mark_site_visit_conflict,
    reset_site_visit_state,
    set_site_visit_date,
    start_site_visit_flow,
)


class TestSiteVisitState:
    """Test site visit state management."""

    def test_get_site_visit_state_creates_default(self):
        """get_site_visit_state should create default state if not exists."""
        event_entry = {}
        state = get_site_visit_state(event_entry)

        assert state["status"] == "idle"
        assert state["date_iso"] is None
        assert state["time_slot"] is None
        assert state["proposed_slots"] == []
        assert state["initiated_at_step"] is None
        assert state["has_event_conflict"] is False
        assert "site_visit_state" in event_entry

    def test_get_site_visit_state_preserves_existing(self):
        """get_site_visit_state should preserve existing state."""
        event_entry = {
            "site_visit_state": {
                "status": "scheduled",
                "date_iso": "2026-02-10",
                "time_slot": "14:00",
            }
        }
        state = get_site_visit_state(event_entry)

        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-10"
        assert state["time_slot"] == "14:00"

    def test_start_site_visit_flow(self):
        """Starting site visit should go directly to date_pending (venue-wide)."""
        event_entry = {}
        state = start_site_visit_flow(event_entry, initiated_at_step=4)

        assert state["status"] == "date_pending"
        assert state["initiated_at_step"] == 4
        assert state["date_iso"] is None
        assert state["proposed_slots"] == []

    def test_set_site_visit_date(self):
        """Setting date should transition to scheduled status."""
        event_entry = {}
        start_site_visit_flow(event_entry)

        set_site_visit_date(event_entry, "2026-02-15", "14:00")
        state = get_site_visit_state(event_entry)

        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-15"
        assert state["time_slot"] == "14:00"

    def test_is_site_visit_active(self):
        """is_site_visit_active should return True for date_pending."""
        event_entry = {}

        # idle -> not active
        assert is_site_visit_active(event_entry) is False

        # date_pending -> active
        start_site_visit_flow(event_entry)
        assert is_site_visit_active(event_entry) is True

        # scheduled -> not active
        set_site_visit_date(event_entry, "2026-02-15")
        assert is_site_visit_active(event_entry) is False

    def test_is_site_visit_scheduled(self):
        """is_site_visit_scheduled should return True only when scheduled."""
        event_entry = {}

        assert is_site_visit_scheduled(event_entry) is False

        start_site_visit_flow(event_entry)
        assert is_site_visit_scheduled(event_entry) is False

        set_site_visit_date(event_entry, "2026-02-15")
        assert is_site_visit_scheduled(event_entry) is True

    def test_complete_site_visit(self):
        """complete_site_visit should set status to completed."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        complete_site_visit(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "completed"

    def test_cancel_site_visit(self):
        """cancel_site_visit should set status to cancelled."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        cancel_site_visit(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "cancelled"

    def test_mark_site_visit_conflict(self):
        """mark_site_visit_conflict should set has_event_conflict flag."""
        event_entry = {}
        start_site_visit_flow(event_entry)
        set_site_visit_date(event_entry, "2026-02-15")

        mark_site_visit_conflict(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["has_event_conflict"] is True

    def test_reset_site_visit_state(self):
        """reset_site_visit_state should clear all state."""
        event_entry = {}
        start_site_visit_flow(event_entry, initiated_at_step=5)
        set_site_visit_date(event_entry, "2026-02-15", "14:00")
        mark_site_visit_conflict(event_entry)

        reset_site_visit_state(event_entry)
        state = get_site_visit_state(event_entry)

        assert state["status"] == "idle"
        assert state["date_iso"] is None
        assert state["time_slot"] is None
        assert state["proposed_slots"] == []
        assert state["initiated_at_step"] is None
        assert state["has_event_conflict"] is False


class TestSiteVisitIntentDetection:
    """Test site visit intent detection."""

    def test_site_visit_keywords_in_classifier(self):
        """site_visit_request keywords should be recognized."""
        from detection.intent.classifier import _detect_qna_types

        # Test various site visit request phrases
        test_phrases = [
            "I would like to book a site visit",
            "Can we schedule a visit to see the room?",
            "We want to see the venue before booking",
            "Can I visit beforehand?",
            "I'd like to tour the room",
        ]

        for phrase in test_phrases:
            qna_types = _detect_qna_types(phrase.lower())
            assert "site_visit_request" in qna_types or "site_visit_overview" in qna_types, \
                f"Expected site visit intent in '{phrase}', got {qna_types}"

    def test_site_visit_step_mapping(self):
        """site_visit_request should map to step 0 (cross-step)."""
        from detection.intent.classifier import QNA_TYPE_TO_STEP

        assert QNA_TYPE_TO_STEP.get("site_visit_request") == 0  # Cross-step


class TestSiteVisitHandler:
    """Test site visit handler integration."""

    def test_is_site_visit_intent_detection(self):
        """is_site_visit_intent should detect site visit from detection result."""
        from detection.unified import UnifiedDetectionResult
        from workflows.common.site_visit_handler import is_site_visit_intent

        # No detection result
        assert is_site_visit_intent(None) is False

        # Detection without site visit
        result = UnifiedDetectionResult(intent="general_qna", qna_types=[])
        assert is_site_visit_intent(result) is False

        # Detection with site_visit_request
        result = UnifiedDetectionResult(intent="general_qna", qna_types=["site_visit_request"])
        assert is_site_visit_intent(result) is True

        # Detection with site_visit_overview - should NOT trigger booking
        # (site_visit_overview is for info questions like "do you offer tours?")
        result = UnifiedDetectionResult(intent="general_qna", qna_types=["site_visit_overview"])
        assert is_site_visit_intent(result) is False

        # Detection with Site Visit step anchor
        result = UnifiedDetectionResult(intent="general_qna", step_anchor="Site Visit")
        assert is_site_visit_intent(result) is True


class TestSiteVisitConflictDetection:
    """Test site visit conflict detection with events."""

    def test_blocked_dates_includes_event_date(self):
        """Event date should be in blocked dates."""
        from workflows.common.site_visit_handler import _get_blocked_dates

        # Provide empty db to avoid loading from file
        db = {"events": []}
        event_entry = {"chosen_date": "15.02.2026"}
        blocked = _get_blocked_dates(event_entry, db=db)

        assert "2026-02-15" in blocked

    def test_blocked_dates_handles_iso_format(self):
        """ISO format dates should also work."""
        from workflows.common.site_visit_handler import _get_blocked_dates

        db = {"events": []}
        event_entry = {"user_info": {"date": "2026-03-20"}}
        blocked = _get_blocked_dates(event_entry, db=db)

        assert "2026-03-20" in blocked

    def test_slot_generation_excludes_blocked_dates(self):
        """Generated slots should not include blocked dates."""
        from workflows.common.site_visit_handler import _generate_visit_slots

        event_entry = {"chosen_date": "15.02.2026"}
        blocked = {"2026-02-14", "2026-02-13"}  # Block dates before event

        slots = _generate_visit_slots(event_entry, blocked)

        # Verify no slot is on a blocked date
        for slot in slots:
            date_part = slot.split(" at ")[0]  # "12.02.2026"
            day, month, year = map(int, date_part.split("."))
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            assert date_iso not in blocked, f"Slot {slot} is on blocked date {date_iso}"


class TestSiteVisitConflictWithMultipleEvents:
    """Test site visit conflict detection with multiple events in database."""

    def _create_mock_db(self, events_data):
        """Helper to create a mock database with events."""
        events = []
        for i, data in enumerate(events_data):
            events.append({
                "event_id": f"evt-{i}",
                "status": data.get("status", "Lead"),
                "chosen_date": data.get("chosen_date"),
                "event_data": {
                    "Event Date": data.get("event_date"),
                    "Email": f"client{i}@example.com",
                },
            })
        return {"events": events, "clients": {}, "tasks": []}

    def test_get_event_dates_returns_all_dates(self):
        """get_event_dates should return dates from all events."""
        from workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
            {"event_date": "20.02.2026"},  # From event_data
        ])

        dates = get_event_dates(db)

        assert "2026-02-10" in dates
        assert "2026-02-15" in dates
        assert "2026-02-20" in dates
        assert len(dates) == 3

    def test_get_event_dates_excludes_cancelled(self):
        """get_event_dates should exclude cancelled events."""
        from workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026", "status": "Lead"},
            {"chosen_date": "15.02.2026", "status": "Cancelled"},
            {"chosen_date": "20.02.2026", "status": "Confirmed"},
        ])

        dates = get_event_dates(db, exclude_cancelled=True)

        assert "2026-02-10" in dates
        assert "2026-02-15" not in dates  # Cancelled
        assert "2026-02-20" in dates
        assert len(dates) == 2

    def test_get_event_dates_can_include_cancelled(self):
        """get_event_dates with exclude_cancelled=False includes all."""
        from workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026", "status": "Lead"},
            {"chosen_date": "15.02.2026", "status": "Cancelled"},
        ])

        dates = get_event_dates(db, exclude_cancelled=False)

        assert "2026-02-10" in dates
        assert "2026-02-15" in dates
        assert len(dates) == 2

    def test_get_event_dates_excludes_specific_event(self):
        """get_event_dates should exclude specified event_id."""
        from workflows.io.database import get_event_dates

        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
        ])

        dates = get_event_dates(db, exclude_event_id="evt-0")

        assert "2026-02-10" not in dates  # Excluded
        assert "2026-02-15" in dates
        assert len(dates) == 1

    def test_blocked_dates_includes_all_events_from_db(self):
        """_get_blocked_dates should block all event dates from database."""
        from workflows.common.site_visit_handler import _get_blocked_dates

        # Create db with multiple events
        db = self._create_mock_db([
            {"chosen_date": "10.02.2026"},
            {"chosen_date": "15.02.2026"},
            {"chosen_date": "20.02.2026"},
        ])

        # Current event (not in db yet)
        event_entry = {"chosen_date": "25.02.2026"}

        blocked = _get_blocked_dates(event_entry, db=db)

        # Should include all dates
        assert "2026-02-10" in blocked
        assert "2026-02-15" in blocked
        assert "2026-02-20" in blocked
        assert "2026-02-25" in blocked  # Current event
        assert len(blocked) == 4

    def test_blocked_dates_with_db_loader_injection(self):
        """Test db loader injection for testing."""
        from workflows.common.site_visit_handler import (
            _get_blocked_dates,
            set_db_loader,
        )

        # Create mock db
        mock_db = self._create_mock_db([
            {"chosen_date": "10.03.2026"},
            {"chosen_date": "15.03.2026"},
        ])

        # Set the db loader
        set_db_loader(lambda: mock_db)

        try:
            event_entry = {}  # No date, just checking db loader works
            blocked = _get_blocked_dates(event_entry)

            assert "2026-03-10" in blocked
            assert "2026-03-15" in blocked
        finally:
            # Reset loader
            set_db_loader(None)

    def test_slot_generation_avoids_all_event_dates(self):
        """Slot generation should avoid all event dates from database."""
        from workflows.common.site_visit_handler import _generate_visit_slots

        # Current event is on 28.02.2026
        # Other events are on 20.02 and 21.02
        event_entry = {"chosen_date": "28.02.2026"}

        # Block dates that other events occupy
        blocked = {"2026-02-20", "2026-02-21", "2026-02-28"}

        slots = _generate_visit_slots(event_entry, blocked)

        # Verify no slot is on a blocked date
        for slot in slots:
            date_part = slot.split(" at ")[0]
            day, month, year = map(int, date_part.split("."))
            date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            assert date_iso not in blocked, f"Slot {slot} is on blocked date {date_iso}"

    def test_get_site_visits_on_date(self):
        """get_site_visits_on_date should find events with scheduled site visits."""
        from workflows.io.database import get_site_visits_on_date

        db = {
            "events": [
                {
                    "event_id": "evt-1",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-10",
                    },
                },
                {
                    "event_id": "evt-2",
                    "site_visit_state": {
                        "status": "scheduled",
                        "date_iso": "2026-02-15",
                    },
                },
                {
                    "event_id": "evt-3",
                    "site_visit_state": {
                        "status": "proposed",  # Not scheduled
                        "date_iso": "2026-02-10",
                    },
                },
            ],
            "clients": {},
            "tasks": [],
        }

        # Find visits on 2026-02-10
        visits = get_site_visits_on_date(db, "2026-02-10")

        assert len(visits) == 1  # Only evt-1, not evt-3 (not scheduled)
        assert visits[0]["event_id"] == "evt-1"

        # Find visits on 2026-02-15
        visits = get_site_visits_on_date(db, "2026-02-15")
        assert len(visits) == 1
        assert visits[0]["event_id"] == "evt-2"

        # No visits on 2026-02-20
        visits = get_site_visits_on_date(db, "2026-02-20")
        assert len(visits) == 0

    def test_conflict_rule_site_visit_blocked_on_event_day(self):
        """Site visits cannot be booked on event days."""
        from workflows.common.site_visit_handler import _get_blocked_dates

        # Event on 15.02.2026
        db = self._create_mock_db([{"chosen_date": "15.02.2026"}])
        event_entry = {}

        blocked = _get_blocked_dates(event_entry, db=db)

        # 15.02.2026 is blocked for site visits
        assert "2026-02-15" in blocked

    def test_conflict_rule_event_allowed_on_site_visit_day(self):
        """Events CAN be booked on site visit days (triggers notification)."""
        from workflows.io.database import get_site_visits_on_date

        # Client has site visit scheduled for 10.02.2026
        db = {
            "events": [{
                "event_id": "evt-1",
                "site_visit_state": {
                    "status": "scheduled",
                    "date_iso": "2026-02-10",
                },
            }],
            "clients": {},
            "tasks": [],
        }

        # When booking an event on that day, check for site visit conflicts
        visits = get_site_visits_on_date(db, "2026-02-10")

        # Should find the site visit - caller can create manager notification
        assert len(visits) == 1

        # The event CAN still be booked (not blocked)
        # The site visit conflict just triggers a notification


class TestSiteVisitVenueWide:
    """Test that site visits are venue-wide (no room needed)."""

    def test_no_room_in_state(self):
        """Site visit state should not require room_id."""
        event_entry = {}
        state = start_site_visit_flow(event_entry, initiated_at_step=3)

        # Room fields should be deprecated (None or missing)
        assert state.get("room_id") is None
        # Status should go directly to date_pending (no room_pending)
        assert state["status"] == "date_pending"

    def test_deprecated_room_functions_return_none(self):
        """Deprecated room functions should return None/no-op."""
        from workflows.common.site_visit_state import (
            get_default_room_for_site_visit,
            get_site_visit_room,
            set_site_visit_room,
        )

        event_entry = {"locked_room_id": "Room A"}

        # These functions are deprecated and should return None
        assert get_site_visit_room(event_entry) is None
        assert get_default_room_for_site_visit(event_entry) is None

        # set_site_visit_room should be a no-op
        set_site_visit_room(event_entry, "Room B")
        state = get_site_visit_state(event_entry)
        assert state.get("room_id") is None  # Should not have been set


class TestSiteVisitTimeRangeMode:
    """Test site visit time range mode (dynamic slot generation)."""

    def test_generate_slots_from_range_30min(self):
        """Generate 30-minute interval slots from time range."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        # Mock config to return 10:00-14:00 range with 30-min slots
        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=14):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=30):
                    booked_slots: set = set()  # Empty set with 3-tuple type
                    slots = _generate_time_slots_from_range(booked_slots, "2026-02-10")

        # Should generate: 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30
        expected = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]
        assert slots == expected

    def test_generate_slots_from_range_60min(self):
        """Generate 60-minute interval slots from time range."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        # Mock config to return 9:00-13:00 range with 60-min slots
        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=9):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=13):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=60):
                    booked_slots: set = set()  # Empty set with 3-tuple type
                    slots = _generate_time_slots_from_range(booked_slots, "2026-02-10")

        # Should generate: 09:00, 10:00, 11:00, 12:00
        expected = ["09:00", "10:00", "11:00", "12:00"]
        assert slots == expected

    def test_generate_slots_excludes_booked(self):
        """Generated slots should exclude already-booked slots (duration-aware)."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=12):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=30):
                    # Book the 10:30 slot with 30-min duration
                    booked_slots = {("2026-02-10", "10:30", 30)}
                    slots = _generate_time_slots_from_range(booked_slots, "2026-02-10")

        # Should NOT include 10:30 (exact match)
        assert "10:30" not in slots
        # 10:00 slot (10:00-10:30) is adjacent to booked (10:30-11:00), should be available
        assert "10:00" in slots
        # 11:00 slot (11:00-11:30) is after booked (10:30-11:00), should be available
        assert "11:00" in slots

    def test_default_holidays_recognized(self):
        """Default holidays should be recognized."""
        from workflows.common.site_visit_handler import _is_default_holiday
        from datetime import datetime

        # New Year's Day
        assert _is_default_holiday(datetime(2026, 1, 1)) is True
        # Christmas
        assert _is_default_holiday(datetime(2026, 12, 25)) is True
        # Boxing Day
        assert _is_default_holiday(datetime(2026, 12, 26)) is True
        # New Year's Eve
        assert _is_default_holiday(datetime(2026, 12, 31)) is True
        # Independence Day
        assert _is_default_holiday(datetime(2026, 7, 4)) is True

        # Regular day - not a holiday
        assert _is_default_holiday(datetime(2026, 2, 10)) is False

    def test_add_working_days_skips_weekends(self):
        """_add_working_days should skip weekends."""
        from workflows.common.site_visit_handler import _add_working_days
        from datetime import datetime

        # Start on a Friday (2026-02-06)
        start = datetime(2026, 2, 6)
        blocked = set()

        # Add 1 working day -> should skip Sat/Sun -> Monday (2026-02-09)
        result = _add_working_days(start, 1, blocked)
        assert result.date().isoformat() == "2026-02-09"

    def test_add_working_days_skips_holidays(self):
        """_add_working_days should skip default holidays."""
        from workflows.common.site_visit_handler import _add_working_days
        from datetime import datetime

        # Start on Dec 23 (Wednesday in 2026)
        start = datetime(2026, 12, 23)
        blocked = set()

        # Add 3 working days:
        # - Dec 24 (Thu) = 1
        # - Dec 25 (Fri) = HOLIDAY (Christmas), skip
        # - Dec 26 (Sat) = weekend (also Boxing Day), skip
        # - Dec 27 (Sun) = weekend, skip
        # - Dec 28 (Mon) = 2
        # - Dec 29 (Tue) = 3
        result = _add_working_days(start, 3, blocked)
        assert result.date().isoformat() == "2026-12-29"

    def test_add_working_days_skips_blocked_dates(self):
        """_add_working_days should skip custom blocked dates."""
        from workflows.common.site_visit_handler import _add_working_days
        from datetime import datetime

        # Start on Monday (2026-02-02)
        start = datetime(2026, 2, 2)
        # Block Tuesday and Wednesday
        blocked = {"2026-02-03", "2026-02-04"}

        # Add 1 working day:
        # - Feb 3 (Tue) = blocked, skip
        # - Feb 4 (Wed) = blocked, skip
        # - Feb 5 (Thu) = 1
        result = _add_working_days(start, 1, blocked)
        assert result.date().isoformat() == "2026-02-05"

    def test_backward_compatibility_legacy_mode(self):
        """Legacy mode should use default_slots list."""
        from workflows.common.site_visit_handler import _generate_time_slots_for_date
        from unittest.mock import patch

        event_entry = {}

        # Mock legacy mode (time_range_mode = False)
        with patch("workflows.common.site_visit_handler.is_site_visit_time_range_mode", return_value=False):
            with patch("workflows.common.site_visit_handler.get_site_visit_slots", return_value=[10, 14, 16]):
                with patch("workflows.common.site_visit_handler._get_booked_site_visit_slots", return_value=set()):
                    with patch("workflows.common.site_visit_handler._has_any_room_available_for_slot", return_value=True):
                        slots = _generate_time_slots_for_date(event_entry, "2026-02-10")

        # Should return legacy slots at :00 mark
        assert slots == ["10:00", "14:00", "16:00"]

    def test_time_range_mode_generates_dynamic_slots(self):
        """Time range mode should generate dynamic slots."""
        from workflows.common.site_visit_handler import _generate_time_slots_for_date
        from unittest.mock import patch

        event_entry = {}

        # Mock range mode (time_range_mode = True)
        with patch("workflows.common.site_visit_handler.is_site_visit_time_range_mode", return_value=True):
            with patch("workflows.common.site_visit_handler._generate_time_slots_from_range", return_value=["10:00", "10:30", "11:00"]) as mock_gen:
                with patch("workflows.common.site_visit_handler._get_booked_site_visit_slots", return_value=set()):
                    with patch("workflows.common.site_visit_handler._has_any_room_available_for_slot", return_value=True):
                        slots = _generate_time_slots_for_date(event_entry, "2026-02-10")

        # Should call the dynamic generator
        mock_gen.assert_called_once()
        assert slots == ["10:00", "10:30", "11:00"]


class TestDurationOverlapDetection:
    """Test duration-aware slot overlap detection.

    This verifies that the system correctly identifies overlapping time windows
    when bookings have durations, not just exact start times.

    The classic interval overlap formula is:
    Two windows [A_start, A_end] and [B_start, B_end] overlap if:
    A_start < B_end AND B_start < A_end
    """

    def test_time_to_minutes_basic(self):
        """_time_to_minutes should convert HH:MM to minutes correctly."""
        from workflows.common.site_visit_handler import _time_to_minutes

        assert _time_to_minutes("00:00") == 0
        assert _time_to_minutes("10:00") == 600
        assert _time_to_minutes("10:30") == 630
        assert _time_to_minutes("14:45") == 885
        assert _time_to_minutes("23:59") == 1439

    def test_time_to_minutes_validation(self):
        """_time_to_minutes should raise ValueError for invalid input."""
        from workflows.common.site_visit_handler import _time_to_minutes
        import pytest

        # Invalid format
        with pytest.raises(ValueError):
            _time_to_minutes("10:00 AM")
        with pytest.raises(ValueError):
            _time_to_minutes("10")
        with pytest.raises(ValueError):
            _time_to_minutes("")
        with pytest.raises(ValueError):
            _time_to_minutes(None)  # type: ignore
        # Out of range
        with pytest.raises(ValueError):
            _time_to_minutes("25:00")
        with pytest.raises(ValueError):
            _time_to_minutes("10:60")

    def test_no_overlap_separate_windows(self):
        """Non-overlapping windows should both be available."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # 10:00-10:45 and 11:00-11:45 don't overlap
        booked = {("2026-02-10", "10:00", 45)}
        assert not _slot_overlaps_with_booked("11:00", booked, "2026-02-10", 45)

    def test_overlap_partial_after(self):
        """Partially overlapping windows should be detected (candidate starts during booked)."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # 10:00-10:45 overlaps with 10:30-11:15
        booked = {("2026-02-10", "10:00", 45)}
        assert _slot_overlaps_with_booked("10:30", booked, "2026-02-10", 45)

    def test_overlap_partial_before(self):
        """Partially overlapping windows should be detected (candidate ends during booked)."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # 10:30-11:15 overlaps with 11:00-11:45
        booked = {("2026-02-10", "11:00", 45)}
        assert _slot_overlaps_with_booked("10:30", booked, "2026-02-10", 45)

    def test_overlap_contained(self):
        """Window contained within another should be detected."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # Candidate 10:15-10:45 is contained within booked 10:00-11:00
        booked = {("2026-02-10", "10:00", 60)}
        assert _slot_overlaps_with_booked("10:15", booked, "2026-02-10", 30)

    def test_overlap_containing(self):
        """Window containing another should be detected."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # Candidate 10:00-11:00 contains booked 10:15-10:45
        booked = {("2026-02-10", "10:15", 30)}
        assert _slot_overlaps_with_booked("10:00", booked, "2026-02-10", 60)

    def test_overlap_exact_same_window(self):
        """Exact same window should be detected as overlap."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        booked = {("2026-02-10", "10:00", 45)}
        assert _slot_overlaps_with_booked("10:00", booked, "2026-02-10", 45)

    def test_adjacent_windows_no_overlap(self):
        """Adjacent (touching) windows should NOT overlap."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        # 10:00-10:45 and 10:45-11:30 are adjacent, not overlapping
        # The formula is A_start < B_end AND B_start < A_end
        # A=[10:00, 10:45], B=[10:45, 11:30]
        # 10:45 < 10:45 is FALSE, so no overlap
        booked = {("2026-02-10", "10:00", 45)}
        assert not _slot_overlaps_with_booked("10:45", booked, "2026-02-10", 45)

    def test_different_date_no_overlap(self):
        """Same time on different date should not conflict."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        booked = {("2026-02-10", "10:00", 45)}
        assert not _slot_overlaps_with_booked("10:00", booked, "2026-02-11", 45)

    def test_multiple_bookings_one_overlaps(self):
        """Should detect overlap even with multiple bookings where only one overlaps."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        booked = {
            ("2026-02-10", "09:00", 45),  # 09:00-09:45 - no overlap
            ("2026-02-10", "10:00", 45),  # 10:00-10:45 - OVERLAPS with 10:30
            ("2026-02-10", "12:00", 45),  # 12:00-12:45 - no overlap
        }
        assert _slot_overlaps_with_booked("10:30", booked, "2026-02-10", 45)

    def test_multiple_bookings_none_overlap(self):
        """Should not detect overlap when no bookings overlap."""
        from workflows.common.site_visit_handler import _slot_overlaps_with_booked

        booked = {
            ("2026-02-10", "09:00", 45),  # 09:00-09:45
            ("2026-02-10", "12:00", 45),  # 12:00-12:45
        }
        assert not _slot_overlaps_with_booked("10:00", booked, "2026-02-10", 45)

    def test_generate_slots_excludes_overlapping(self):
        """Generated slots should exclude all overlapping windows."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        # 10:00 booked with 45-min duration
        # Slot duration is also 45 min
        # So 10:00-10:45 is booked
        # 10:45 starts where booked ends (adjacent, not overlapping)
        booked = {("2026-02-10", "10:00", 45)}

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=12):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=45):
                    slots = _generate_time_slots_from_range(booked, "2026-02-10")

        # 10:00 is booked, should not appear
        assert "10:00" not in slots
        # 10:45 starts where 10:00-10:45 ends (adjacent), should be available
        assert "10:45" in slots

    def test_generate_slots_with_shorter_booked_duration(self):
        """When booked slot has shorter duration than new slots, should still detect overlap."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        # 10:00 booked with 30-min duration (10:00-10:30)
        # New slots are 45 min
        # 10:00-10:45 overlaps with booked 10:00-10:30
        # But 10:30-11:15 also overlaps with booked 10:00-10:30 (booked ends at 10:30, candidate starts at 10:30 - adjacent)
        booked = {("2026-02-10", "10:00", 30)}

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=10):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=12):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=45):
                    slots = _generate_time_slots_from_range(booked, "2026-02-10")

        # 10:00 slot (10:00-10:45) overlaps with booked (10:00-10:30)
        assert "10:00" not in slots
        # 10:45 slot (10:45-11:30) does NOT overlap with booked (10:00-10:30) - starts after booked ends
        assert "10:45" in slots

    def test_midnight_crossing_slots_rejected(self):
        """Slots that would cross midnight should not be generated."""
        from workflows.common.site_visit_handler import _generate_time_slots_from_range
        from unittest.mock import patch

        booked: set = set()

        with patch("workflows.common.site_visit_handler.get_site_visit_range_start_hour", return_value=22):
            with patch("workflows.common.site_visit_handler.get_site_visit_range_end_hour", return_value=24):
                with patch("workflows.common.site_visit_handler.get_site_visit_slot_duration", return_value=60):
                    slots = _generate_time_slots_from_range(booked, "2026-02-10")

        # 22:00-23:00 is valid
        assert "22:00" in slots
        # 23:00-24:00 is valid (ends exactly at midnight)
        assert "23:00" in slots
        # No slots after 23:00 because 24:00 would be the end_hour

    def test_duration_stored_with_booking(self):
        """Duration should be stored when booking a site visit."""
        from workflows.common.site_visit_state import set_site_visit_date, get_site_visit_state
        from unittest.mock import patch

        event_entry = {}

        # Mock range mode with 45-min duration - patch where the function is used
        with patch("workflows.io.config_store.is_site_visit_time_range_mode", return_value=True):
            with patch("workflows.io.config_store.get_site_visit_slot_duration", return_value=45):
                set_site_visit_date(event_entry, "2026-02-10", "10:00")

        state = get_site_visit_state(event_entry)
        assert state.get("duration_minutes") == 45

    def test_legacy_booking_defaults_to_60_min(self):
        """Legacy bookings (no stored duration) should default to 60 min."""
        from workflows.common.site_visit_state import set_site_visit_date, get_site_visit_state
        from unittest.mock import patch

        event_entry = {}

        # Mock legacy mode - patch where the function is used
        with patch("workflows.io.config_store.is_site_visit_time_range_mode", return_value=False):
            set_site_visit_date(event_entry, "2026-02-10", "10:00")

        state = get_site_visit_state(event_entry)
        assert state.get("duration_minutes") == 60


class TestConfigStoreAccessors:
    """Test new config store accessor functions."""

    def test_get_site_visit_range_start_hour_default(self):
        """Should return default start hour."""
        from workflows.io.config_store import get_site_visit_range_start_hour

        # Default is 10
        result = get_site_visit_range_start_hour()
        assert isinstance(result, int)
        assert result == 10

    def test_get_site_visit_range_end_hour_default(self):
        """Should return default end hour."""
        from workflows.io.config_store import get_site_visit_range_end_hour

        # Default is 22
        result = get_site_visit_range_end_hour()
        assert isinstance(result, int)
        assert result == 22

    def test_get_site_visit_slot_duration_default(self):
        """Should return default slot duration."""
        from workflows.io.config_store import get_site_visit_slot_duration

        # Default is 30
        result = get_site_visit_slot_duration()
        assert isinstance(result, int)
        assert result == 30

    def test_get_site_visit_default_working_days_ahead_default(self):
        """Should return default working days ahead."""
        from workflows.io.config_store import get_site_visit_default_working_days_ahead

        # Default is 3
        result = get_site_visit_default_working_days_ahead()
        assert isinstance(result, int)
        assert result == 3

    def test_is_site_visit_time_range_mode_default(self):
        """Should return default time range mode (False)."""
        from workflows.io.config_store import is_site_visit_time_range_mode

        # Default is False (legacy mode)
        result = is_site_visit_time_range_mode()
        assert result is False
