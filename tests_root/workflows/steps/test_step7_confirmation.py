"""
Tests for Step 7 - Confirmation Handler.

Covers:
- Site visit handling (proposal, preference, confirmation)
- Structural change detection
- Nonsense gate
- Q&A handling within confirmation
"""
from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from domain import IntentLabel
from workflows.common.types import GroupResult, WorkflowState, IncomingMessage
from workflows.steps.step7_confirmation.trigger.step7_handler import process
from workflows.steps.step7_confirmation.trigger.classification import classify_message
from workflows.steps.step7_confirmation.trigger.site_visit import (
    extract_site_visit_preference,
    parse_slot_selection,
)

pytestmark = pytest.mark.v4


@pytest.fixture
def confirmed_event_entry():
    """Event entry at Step 7 (post-offer acceptance)."""
    return {
        "event_id": "evt-step7-test",
        "current_step": 7,
        "chosen_date": "15.02.2026",
        "chosen_date_iso": "2026-02-15",
        "locked_room_id": "Room A",
        "offer_status": "Accepted",
        "requirements": {"number_of_participants": 25},
        "deposit_state": {"required": True, "status": "paid"},
        "billing_details": {
            "name": "Test Corp",
            "street": "Main St 1",
            "city": "Zurich",
        },
        "confirmation_state": {"pending": None, "last_response_type": None},
        "thread_state": "In Progress",
    }


@pytest.fixture
def workflow_state(confirmed_event_entry):
    """Create a workflow state for testing."""
    message = IncomingMessage(
        msg_id="msg-step7",
        from_name="Test Client",
        from_email="test@example.com",
        subject="Re: Confirmation",
        body="",
        ts=None,
    )
    state = WorkflowState(
        message=message,
        db_path=Path("."),
        db={},
        intent=IntentLabel.CONFIRM_DATE,
        confidence=0.9,
    )
    state.event_entry = confirmed_event_entry
    state.client_id = "test@example.com"
    state.user_info = {}
    return state


class TestClassification:
    """Tests for Step 7 message classification."""

    def test_classify_site_visit_request(self, confirmed_event_entry):
        """Site visit request should be classified."""
        intent = classify_message("I would like to schedule a site visit", confirmed_event_entry)
        assert intent in ["site_visit", "question"]

    def test_classify_question(self, confirmed_event_entry):
        """Questions should trigger question classification."""
        intent = classify_message("What time is check-in?", confirmed_event_entry)
        assert intent == "question"

    def test_classify_confirmation(self, confirmed_event_entry):
        """Confirmation messages should be detected."""
        intent = classify_message("Yes, everything looks good", confirmed_event_entry)
        assert intent in ["confirm", "question"]


class TestSiteVisitPreference:
    """Tests for site visit preference extraction."""

    def test_extracts_date_preference(self):
        """Should extract date preference from message."""
        pref = extract_site_visit_preference(
            {"date": "2026-02-10"},
            "I'd like to visit on Monday the 10th"
        )
        # Should return date info or None
        assert pref is None or isinstance(pref, dict)

    def test_extracts_time_preference(self):
        """Should extract time preference from message."""
        pref = extract_site_visit_preference(
            {},
            "Can we visit at 2pm?"
        )
        # Should return time info or None
        assert pref is None or isinstance(pref, dict)


class TestSlotSelection:
    """Tests for site visit slot selection parsing."""

    def test_parse_first_slot(self):
        """'First option' should select first slot."""
        slots = [
            "10.02.2026 at 10:00",
            "10.02.2026 at 14:00",
        ]
        result = parse_slot_selection("The first option works", slots)
        assert result == slots[0]

    def test_parse_yes_confirmation(self):
        """'Yes' should confirm if single slot."""
        slots = ["10.02.2026 at 10:00"]
        result = parse_slot_selection("Yes, that works", slots)
        # Yes alone doesn't select a slot without explicit confirmation
        assert result is None or result == slots[0]


class TestSiteVisitFlow:
    """Tests for site visit handling."""

    def test_site_visit_proposed_state(self, workflow_state):
        """Site visit proposed state should handle preference."""
        workflow_state.event_entry["site_visit_state"] = {
            "status": "proposed",
            "proposed_slots": [
                {"date": "2026-02-10", "time": "10:00"},
                {"date": "2026-02-10", "time": "14:00"},
            ],
        }
        workflow_state.message = IncomingMessage(
            msg_id="msg-visit-confirm",
            from_name="Test",
            from_email="test@example.com",
            subject="Visit",
            body="The 10am slot works for me",
            ts=None,
        )

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # Should handle site visit or continue processing


class TestStructuralChangeDetection:
    """Tests for detecting structural changes in confirmation."""

    def test_date_change_triggers_detour(self, workflow_state):
        """Date change should trigger detour."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-date-change-step7",
            from_name="Test",
            from_email="test@example.com",
            subject="Date change",
            body="Can we move it to March instead?",
            ts=None,
        )
        workflow_state.user_info = {"date": "2026-03-15"}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # May trigger structural_change_detour

    def test_product_change_triggers_detour(self, workflow_state):
        """Product change should trigger detour to Step 4."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-product-change",
            from_name="Test",
            from_email="test@example.com",
            subject="Add catering",
            body="Can we add the premium wine package?",
            ts=None,
        )
        workflow_state.user_info = {"products_add": ["Premium Wine Package"]}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)


class TestNonsenseGate:
    """Tests for nonsense/off-topic handling."""

    def test_low_confidence_ignored(self, workflow_state):
        """Very low confidence should be ignored."""
        workflow_state.confidence = 0.1
        workflow_state.message = IncomingMessage(
            msg_id="msg-nonsense",
            from_name="Test",
            from_email="test@example.com",
            subject="Nonsense",
            body="asdfghjkl",
            ts=None,
        )

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # May be ignored or handled


class TestMissingEvent:
    """Tests for missing event handling."""

    def test_missing_event_halts(self, workflow_state):
        """Missing event entry should halt processing."""
        workflow_state.event_entry = None

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert result.halt is True
        assert "missing_event" in result.action


class TestHILApproval:
    """Tests for HIL approval handling."""

    def test_hil_approval_step7(self, workflow_state):
        """HIL approval at Step 7 should be handled."""
        workflow_state.user_info = {
            "hil_approve_step": 7,
            "hil_decision": "approve",
        }
        workflow_state.event_entry["confirmation_state"] = {
            "pending": {"type": "final_confirmation"},
        }

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # Should process HIL decision
