"""
Tests for Step 6 - Transition Handler.

Covers:
- Transition blockers (missing date, room, offer status, deposit)
- Transition ready (all prerequisites met)
- Missing event handling
"""
from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock

from backend.domain import IntentLabel
from backend.workflows.common.types import GroupResult, WorkflowState, IncomingMessage
from backend.workflows.steps.step6_transition.trigger.step6_handler import process, _collect_blockers

pytestmark = pytest.mark.v4


@pytest.fixture
def complete_event_entry():
    """Event entry with all prerequisites met."""
    return {
        "event_id": "evt-step6-test",
        "current_step": 6,
        "chosen_date": "15.02.2026",
        "chosen_date_iso": "2026-02-15",
        "locked_room_id": "Room A",
        "offer_status": "Accepted",
        "requirements_hash": "abc123",
        "room_eval_hash": "abc123",  # Same as requirements_hash
        "deposit_state": {"required": True, "status": "paid"},
        "thread_state": "In Progress",
    }


@pytest.fixture
def incomplete_event_entry():
    """Event entry missing prerequisites."""
    return {
        "event_id": "evt-step6-incomplete",
        "current_step": 6,
        "chosen_date": None,  # Missing
        "locked_room_id": None,  # Missing
        "offer_status": "Pending",  # Not accepted
        "thread_state": "In Progress",
    }


@pytest.fixture
def workflow_state(complete_event_entry):
    """Create a workflow state for testing."""
    message = IncomingMessage(
        msg_id="msg-step6",
        from_name="Test Client",
        from_email="test@example.com",
        subject="Transition",
        body="Proceeding to confirmation",
        ts=None,
    )
    state = WorkflowState(
        message=message,
        db_path=Path("."),
        db={},
        intent=IntentLabel.CONFIRM_DATE,
        confidence=0.9,
    )
    state.event_entry = complete_event_entry
    state.client_id = "test@example.com"
    state.user_info = {}
    return state


class TestCollectBlockers:
    """Tests for blocker detection."""

    def test_no_blockers_when_complete(self, complete_event_entry):
        """Complete event should have no blockers."""
        blockers = _collect_blockers(complete_event_entry)
        assert blockers == []

    def test_missing_date_is_blocker(self, complete_event_entry):
        """Missing date should be a blocker."""
        complete_event_entry["chosen_date"] = None
        blockers = _collect_blockers(complete_event_entry)
        assert any("date" in b.lower() for b in blockers)

    def test_missing_room_is_blocker(self, complete_event_entry):
        """Missing room should be a blocker."""
        complete_event_entry["locked_room_id"] = None
        blockers = _collect_blockers(complete_event_entry)
        assert any("room" in b.lower() for b in blockers)

    def test_pending_offer_is_blocker(self, complete_event_entry):
        """Non-accepted offer should be a blocker."""
        complete_event_entry["offer_status"] = "Pending"
        blockers = _collect_blockers(complete_event_entry)
        assert any("offer" in b.lower() for b in blockers)

    def test_unpaid_deposit_is_blocker(self, complete_event_entry):
        """Unpaid deposit should be a blocker."""
        complete_event_entry["deposit_state"] = {"required": True, "status": "pending"}
        blockers = _collect_blockers(complete_event_entry)
        assert any("deposit" in b.lower() for b in blockers)

    def test_hash_mismatch_is_blocker(self, complete_event_entry):
        """Hash mismatch should be a blocker."""
        complete_event_entry["requirements_hash"] = "abc123"
        complete_event_entry["room_eval_hash"] = "xyz789"  # Different
        blockers = _collect_blockers(complete_event_entry)
        assert any("availability" in b.lower() or "requirements" in b.lower() for b in blockers)

    def test_multiple_blockers(self, incomplete_event_entry):
        """Multiple missing items should all be blockers."""
        blockers = _collect_blockers(incomplete_event_entry)
        assert len(blockers) >= 3  # date, room, offer at minimum


class TestTransitionReady:
    """Tests for successful transition."""

    def test_transition_ready_proceeds_to_step7(self, workflow_state):
        """Complete event should transition to Step 7."""
        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert result.action == "transition_ready"
        assert result.payload.get("transition_ready") is True
        assert workflow_state.current_step == 7

    def test_transition_ready_persists(self, workflow_state):
        """Transition should mark persist flag."""
        result = process(workflow_state)

        assert workflow_state.extras.get("persist") is True


class TestTransitionBlocked:
    """Tests for blocked transition."""

    def test_blocked_transition_halts(self, workflow_state, incomplete_event_entry):
        """Incomplete event should block and halt."""
        workflow_state.event_entry = incomplete_event_entry

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert result.action == "transition_blocked"
        assert result.halt is True
        assert len(result.payload.get("blockers", [])) > 0

    def test_blocked_transition_creates_draft(self, workflow_state, incomplete_event_entry):
        """Blocked transition should create a draft message."""
        workflow_state.event_entry = incomplete_event_entry

        process(workflow_state)

        assert len(workflow_state.draft_messages) > 0
        draft = workflow_state.draft_messages[0]
        # Draft should contain relevant context about transition state
        assert "body" in draft


class TestMissingEvent:
    """Tests for missing event handling."""

    def test_missing_event_halts(self, workflow_state):
        """Missing event entry should halt processing."""
        workflow_state.event_entry = None

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert result.halt is True
        assert "missing_event" in result.action
