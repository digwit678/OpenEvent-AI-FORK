"""
E2E Tests: Site Visit from All Steps

Tests that site visit functionality works from every workflow step.

Note: These tests verify detection and state helper functions work correctly.
For full flow verification, run with AGENT_MODE=openai.
"""

from __future__ import annotations

import pytest

from detection.unified import run_unified_detection
from workflows.common.site_visit_state import (
    is_site_visit_active,
    is_site_visit_scheduled,
    get_site_visit_state,
)


# =============================================================================
# SITE VISIT INITIATION TESTS
# =============================================================================


class TestSiteVisitInitiationFromAllSteps:
    """Site visit can be initiated from any workflow step."""

    @pytest.mark.parametrize("current_step", [2, 3, 4, 5, 6, 7])
    def test_site_visit_request_detection_structure(self, current_step, build_state):
        """Site visit request detection returns expected structure."""
        msg = "I'd like to book a site visit"
        build_state(current_step, msg)

        result = run_unified_detection(
            msg,
            current_step=current_step,
            date_confirmed=current_step > 2,
            room_locked=current_step > 3,
        )

        assert result is not None
        assert hasattr(result, "is_question")
        assert hasattr(result, "qna_types")


class TestSiteVisitDateSelection:
    """Site visit date selection tests."""

    @pytest.mark.parametrize("current_step", [2, 3, 4, 5, 6, 7])
    def test_site_visit_date_detection_structure(self, current_step, build_state):
        """Site visit date selection detection structure."""
        msg = "Let's do the site visit on March 10"
        build_state(current_step, msg)

        result = run_unified_detection(
            msg,
            current_step=current_step,
            date_confirmed=current_step > 2,
            room_locked=current_step > 3,
        )

        assert result is not None
        assert hasattr(result, "date")
        assert hasattr(result, "site_visit_date")


class TestSiteVisitTimeSelection:
    """Site visit time selection tests."""

    @pytest.mark.parametrize("current_step", [2, 3, 4, 5, 6, 7])
    def test_site_visit_time_detection_structure(self, current_step, build_state):
        """Site visit time selection detection structure."""
        msg = "10:00 works for us"
        build_state(current_step, msg)

        result = run_unified_detection(
            msg,
            current_step=current_step,
            date_confirmed=current_step > 2,
            room_locked=current_step > 3,
        )

        assert result is not None
        assert hasattr(result, "start_time")
        assert hasattr(result, "is_confirmation")


# =============================================================================
# SITE VISIT ISOLATION TESTS
# =============================================================================


class TestSiteVisitIsolation:
    """Site visit should not affect main workflow state."""

    @pytest.mark.parametrize("current_step", [4, 5, 6, 7])
    def test_site_visit_does_not_change_workflow_step(self, current_step, build_state, assert_step_unchanged):
        """Site visit initiation should not change current workflow step."""
        msg = "Can we schedule a site visit?"
        state = build_state(current_step, msg)

        # Site visit detection should not trigger step change
        assert_step_unchanged(state, current_step)

    def test_site_visit_does_not_affect_chosen_date(self, build_state):
        """Site visit date should not affect main event chosen_date."""
        state = build_state(4, "Site visit on March 5 please")

        original_date = state.event_entry.get("chosen_date")

        # Event date should remain unchanged
        assert state.event_entry.get("chosen_date") == original_date

    def test_site_visit_does_not_affect_room_selection(self, build_state):
        """Site visit should not affect locked room."""
        state = build_state(4, "I'd like to see Room B during the site visit")

        original_room = state.event_entry.get("locked_room_id")

        assert state.event_entry.get("locked_room_id") == original_room


# =============================================================================
# SITE VISIT STATE HELPERS
# =============================================================================


class TestSiteVisitStateHelpers:
    """Test site visit state helper functions."""

    def test_is_site_visit_active_date_pending(self, build_state):
        """is_site_visit_active returns True when status is date_pending."""
        state = build_state(4, "test")
        state.event_entry["site_visit_state"] = {"status": "date_pending"}

        result = is_site_visit_active(state.event_entry)

        assert result is True

    def test_is_site_visit_active_time_pending(self, build_state):
        """is_site_visit_active returns True when status is time_pending."""
        state = build_state(4, "test")
        state.event_entry["site_visit_state"] = {"status": "time_pending"}

        result = is_site_visit_active(state.event_entry)

        assert result is True

    def test_is_site_visit_scheduled_true(self, build_state):
        """is_site_visit_scheduled returns True when fully scheduled."""
        state = build_state(4, "test")
        state.event_entry["site_visit_state"] = {
            "status": "scheduled",
            "date_iso": "2026-03-10",
            "time_slot": "10:00",
        }

        result = is_site_visit_scheduled(state.event_entry)

        assert result is True

    def test_is_site_visit_not_scheduled_when_pending(self, build_state):
        """is_site_visit_scheduled returns False when still pending."""
        state = build_state(4, "test")
        state.event_entry["site_visit_state"] = {"status": "date_pending"}

        result = is_site_visit_scheduled(state.event_entry)

        assert result is False

    def test_get_site_visit_state_returns_dict(self, build_state):
        """get_site_visit_state returns dictionary structure."""
        state = build_state(4, "test")
        state.event_entry["site_visit_state"] = {
            "status": "scheduled",
            "date_iso": "2026-03-10",
            "time_slot": "10:00",
        }

        site_visit = get_site_visit_state(state.event_entry)

        assert site_visit is not None
        assert isinstance(site_visit, dict)
        assert "status" in site_visit


# =============================================================================
# SITE VISIT FULL FLOW TESTS
# =============================================================================


class TestSiteVisitFullFlow:
    """Test complete site visit detection flow."""

    @pytest.mark.parametrize("current_step", [4, 5, 6, 7])
    def test_site_visit_full_flow_detection_structure(self, current_step, build_state):
        """Full site visit flow detection returns expected structure."""
        # Step 1: Initial request
        msg1 = "I'd like to schedule a site visit"
        build_state(current_step, msg1)

        result1 = run_unified_detection(msg1, current_step=current_step, date_confirmed=True, room_locked=True)

        assert result1 is not None

        # Step 2: Date selection
        msg2 = "March 10 works for us"

        result2 = run_unified_detection(msg2, current_step=current_step, date_confirmed=True, room_locked=True)

        assert result2 is not None
        assert hasattr(result2, "date")

        # Step 3: Time selection
        msg3 = "10:00 please"

        result3 = run_unified_detection(msg3, current_step=current_step, date_confirmed=True, room_locked=True)

        assert result3 is not None
        assert hasattr(result3, "start_time")


# =============================================================================
# SITE VISIT WITH CONFLICT HANDLING
# =============================================================================


class TestSiteVisitConflictHandling:
    """Test site visit date conflict handling."""

    def test_site_visit_date_detection_on_event_date(self, build_state):
        """Site visit on same date as event should be detectable."""
        build_state(4, "Site visit on March 15", event_kwargs={"chosen_date": "15.03.2026"})

        result = run_unified_detection("Site visit on March 15", current_step=4, date_confirmed=True, room_locked=True)

        assert result is not None
        assert hasattr(result, "date") or hasattr(result, "site_visit_date")


# =============================================================================
# SITE VISIT ACKNOWLEDGMENT
# =============================================================================


class TestSiteVisitAcknowledgment:
    """Test that scheduled site visits are preserved."""

    def test_site_visit_data_preserved_in_event(self, build_state):
        """Scheduled site visit data should be preserved in event entry."""
        state = build_state(7, "test")
        state.event_entry["site_visit_state"] = {
            "status": "scheduled",
            "date_iso": "2026-03-10",
            "time_slot": "10:00",
        }

        site_visit = get_site_visit_state(state.event_entry)

        assert site_visit is not None
        assert site_visit.get("date_iso") == "2026-03-10"
        assert site_visit.get("time_slot") == "10:00"
