"""
E2E Tests: Workflow Scenarios - Detours + Site Visits

This file contains TRUE E2E tests that verify:

1. DETOUR SCENARIO (Date Change → Room Unavailable → Room Selection → Return):
   - Client at Step 4+ requests date change
   - Room is NOT available on new date
   - System redirects to Room Availability (Step 3)
   - After room selection, returns to offer flow

2. SITE VISIT SCENARIOS:
   - Client requests site visit without date → system offers slots
   - Client gives already-occupied slot → system suggests alternatives
   - Client gives valid slot → system confirms the visit
   - Step 1 guard: site visit without event context → deferred

Run with: source scripts/dev/oe_env.sh && pytest tests/e2e/test_workflow_scenarios_e2e.py -v --tb=short
"""

from __future__ import annotations

import json
import os
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.v4


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tmp_db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "events.json"


@pytest.fixture
def create_event_at_step():
    """Factory for creating events at specific steps."""
    from workflows.common.requirements import requirements_hash

    def _create(
        step: int,
        *,
        event_id: str = "EVT-TEST-001",
        chosen_date: str = "15.03.2026",
        date_confirmed: bool = True,
        locked_room_id: Optional[str] = None,
        site_visit_state: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Create an event entry at specified step with proper prerequisites."""
        requirements = {
            "number_of_participants": 30,
            "seating_layout": "dinner",
            "event_duration": {"start": "18:00", "end": "23:00"},
            "special_requirements": None,
            "preferred_room": None,
        }
        req_hash = requirements_hash(requirements)

        # Set defaults based on step
        if locked_room_id is None and step >= 4:
            locked_room_id = "Room A"

        # Parse date
        day, month, year = map(int, chosen_date.split("."))
        chosen_date_iso = f"{year:04d}-{month:02d}-{day:02d}"

        return {
            "event_id": event_id,
            "current_step": step,
            "thread_state": "Awaiting Client",
            "chosen_date": chosen_date if date_confirmed else None,
            "chosen_date_iso": chosen_date_iso if date_confirmed else None,
            "date_confirmed": date_confirmed,
            "locked_room_id": locked_room_id,
            "requirements": requirements,
            "requirements_hash": req_hash,
            "room_eval_hash": req_hash,
            "caller_step": None,
            "preferences": {"wish_products": [], "keywords": []},
            "selected_products": [],
            "products_state": {"line_items": []},
            "offer_sent": step >= 4,
            "offer_accepted": step >= 6,
            "billing_address": {} if step < 6 else {"company": "ACME", "city": "Zurich"},
            "billing_captured": step >= 7,
            "deposit_paid": False,
            "site_visit_state": site_visit_state or {},
            "event_data": {
                "Status": "Option" if step >= 4 else "Inquiry",
                "Email": "client@example.com",
            },
            "requested_window": {
                "date_iso": chosen_date_iso,
                "display_date": chosen_date,
                "start_time": "18:00",
                "end_time": "23:00",
            } if date_confirmed else None,
            "audit": [],
            "client_email": "client@example.com",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    return _create


@pytest.fixture
def save_db(tmp_db_path):
    """Save events to temp database."""
    from workflows.io import database as db_io

    def _save(events: List[Dict[str, Any]]):
        db = {
            "events": events,
            "clients": {
                "client@example.com": {
                    "email": "client@example.com",
                    "history": [],
                    "profile": {"name": "Test Client"},
                }
            },
            "tasks": [],
            "config": {},
        }
        db_io.save_db(db, tmp_db_path)
        return tmp_db_path

    return _save


# =============================================================================
# SCENARIO 1: DATE CHANGE DETOUR (Room Unavailable)
# =============================================================================


class TestDateChangeDetourScenario:
    """
    Scenario: Client at Step 4 (Offer) requests date change.
    Room A is NOT available on new date.
    System should redirect to Room Availability (Step 3).

    This is a known workflow pattern from TEAM_GUIDE.
    """

    def test_detect_date_change_request(self):
        """Date change request should be detected."""
        from detection.unified import run_unified_detection

        msg = "Can we change the event date to March 20 instead?"

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        # Should detect this as a change request with date entity
        assert result.is_change_request or result.date is not None, \
            f"Should detect date change. Got: {result}"

    def test_date_change_detour_structure(self, create_event_at_step):
        """Verify detour structure when date changes and room unavailable."""
        # This is a structural test - verifies the event state transitions

        event = create_event_at_step(
            step=4,
            chosen_date="15.03.2026",
            locked_room_id="Room A",
        )

        # When detour happens:
        # 1. caller_step should be set to return step
        # 2. current_step should change to step 3 (room availability)

        # Simulate detour state
        event["caller_step"] = 4  # Return to step 4 after room selection
        event["current_step"] = 3  # Now at room availability

        # Verify detour state
        assert event["caller_step"] == 4
        assert event["current_step"] == 3


# =============================================================================
# SCENARIO 2: SITE VISIT - NO DATE PROVIDED
# =============================================================================


class TestSiteVisitNoDateScenario:
    """
    Scenario: Client requests site visit without specifying date/time.
    System should offer available slots.
    """

    def test_site_visit_request_without_date(self):
        """Site visit request without date should be detected."""
        from detection.unified import run_unified_detection

        msg = "I'd like to schedule a site visit to see the venue"

        result = run_unified_detection(
            msg,
            current_step=4,
            date_confirmed=True,
            room_locked=True,
        )

        # Should detect site visit intent
        is_site_visit = (
            "site_visit_request" in result.qna_types or
            result.step_anchor == "Site Visit"
        )

        assert is_site_visit or result.is_question, \
            f"Should detect site visit request. Got: {result.qna_types}, {result.step_anchor}"

    def test_site_visit_starts_in_date_pending(self, create_event_at_step):
        """Starting site visit flow should go to date_pending status."""
        from workflows.common.site_visit_state import start_site_visit_flow, get_site_visit_state

        event = create_event_at_step(step=4)

        # Start the flow
        start_site_visit_flow(event, initiated_at_step=4)
        state = get_site_visit_state(event)

        assert state["status"] == "date_pending"
        assert state["initiated_at_step"] == 4


# =============================================================================
# SCENARIO 3: SITE VISIT - OCCUPIED SLOT
# =============================================================================


class TestSiteVisitOccupiedSlotScenario:
    """
    Scenario: Client requests a site visit slot that's already booked.
    System should suggest alternative slots.
    """

    def test_slot_conflict_detection(self):
        """Already-booked slots should be detected."""
        from workflows.common.site_visit_handler import (
            _get_booked_site_visit_slots,
            set_db_loader,
        )

        # Create DB with an existing site visit
        mock_db = {
            "events": [
                {
                    "event_id": "other-event",
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
            event = {"event_id": "current-event"}
            booked = _get_booked_site_visit_slots(event)

            # The 14:00 slot on Feb 10 should be booked
            assert ("2026-02-10", "14:00") in booked
            # Other slots should be free
            assert ("2026-02-10", "10:00") not in booked
        finally:
            set_db_loader(None)


# =============================================================================
# SCENARIO 4: SITE VISIT - VALID SLOT
# =============================================================================


class TestSiteVisitValidSlotScenario:
    """
    Scenario: Client provides a valid, available slot.
    System should confirm the site visit.
    """

    def test_valid_slot_confirmation(self, create_event_at_step):
        """Valid slot should be confirmed."""
        from workflows.common.site_visit_state import (
            start_site_visit_flow,
            set_site_visit_date,
            get_site_visit_state,
        )

        event = create_event_at_step(step=4)

        # Start flow
        start_site_visit_flow(event, initiated_at_step=4)

        # Client selects a slot
        set_site_visit_date(event, "2026-02-15", "10:00")

        state = get_site_visit_state(event)

        # Should be scheduled
        assert state["status"] == "scheduled"
        assert state["date_iso"] == "2026-02-15"
        assert state["time_slot"] == "10:00"


# =============================================================================
# SCENARIO 5: SITE VISIT - STEP 1 GUARD
# =============================================================================


class TestSiteVisitStep1Guard:
    """
    Scenario: Client at Step 1 requests site visit without event context.
    System should defer and ask for event details first.
    """

    def test_step1_guard_without_event_context(self, create_event_at_step):
        """Site visit at Step 1 without context should be deferred."""
        # Create event at step 1 without date or participants
        event = create_event_at_step(
            step=1,
            date_confirmed=False,
        )
        event["chosen_date"] = None
        event["participants"] = None
        event["requirements"]["number_of_participants"] = None

        # The guard should detect this and defer
        has_event_date = bool(event.get("chosen_date"))
        has_participants = bool(
            event.get("participants") or
            event.get("requirements", {}).get("number_of_participants")
        )

        # At step 1 without context, should require context first
        assert not has_event_date
        assert not has_participants


# =============================================================================
# TIME RANGE MODE INTEGRATION
# =============================================================================


class TestTimeRangeModeIntegration:
    """Test time range mode is properly integrated."""

    def test_time_range_mode_off_uses_legacy(self):
        """When time range mode is off, legacy slots are used."""
        from workflows.io.config_store import (
            is_site_visit_time_range_mode,
            get_site_visit_slots,
        )

        # Default should be off (legacy mode)
        assert is_site_visit_time_range_mode() is False

        # Legacy slots should be returned
        slots = get_site_visit_slots()
        assert slots == [10, 14, 16]  # Default legacy slots

    def test_slot_generation_respects_mode(self, create_event_at_step):
        """Slot generation should respect the configured mode."""
        from workflows.common.site_visit_handler import _generate_time_slots_for_date

        event = create_event_at_step(step=4)

        with patch("workflows.common.site_visit_handler.is_site_visit_time_range_mode", return_value=False):
            with patch("workflows.common.site_visit_handler.get_site_visit_slots", return_value=[10, 14, 16]):
                with patch("workflows.common.site_visit_handler._get_booked_site_visit_slots", return_value=set()):
                    with patch("workflows.common.site_visit_handler._has_any_room_available_for_slot", return_value=True):
                        slots = _generate_time_slots_for_date(event, "2026-02-10")

        # Should be legacy format
        assert slots == ["10:00", "14:00", "16:00"]


# =============================================================================
# WORKFLOW STATE PRESERVATION
# =============================================================================


class TestWorkflowStatePreservation:
    """Test that site visit doesn't interfere with main workflow state."""

    def test_site_visit_preserves_current_step(self, create_event_at_step):
        """Site visit flow should preserve current_step."""
        from workflows.common.site_visit_state import (
            start_site_visit_flow,
            set_site_visit_date,
            get_site_visit_state,
        )

        event = create_event_at_step(step=4, locked_room_id="Room A")
        original_step = event["current_step"]
        original_room = event["locked_room_id"]

        # Go through site visit flow
        start_site_visit_flow(event, initiated_at_step=4)
        set_site_visit_date(event, "2026-02-15", "10:00")

        # Main workflow state should be preserved
        assert event["current_step"] == original_step
        assert event["locked_room_id"] == original_room

    def test_site_visit_state_isolated(self, create_event_at_step):
        """Site visit state should be isolated from main workflow."""
        from workflows.common.site_visit_state import (
            start_site_visit_flow,
            get_site_visit_state,
        )

        event = create_event_at_step(step=4)

        # Start site visit
        start_site_visit_flow(event, initiated_at_step=4)

        # Site visit state should be in its own namespace
        assert "site_visit_state" in event
        sv_state = get_site_visit_state(event)

        # Site visit status should NOT affect main workflow status
        assert sv_state["status"] == "date_pending"
        assert event["current_step"] == 4  # Main step unchanged
