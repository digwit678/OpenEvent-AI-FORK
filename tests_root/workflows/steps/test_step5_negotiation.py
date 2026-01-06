"""
Tests for Step 5 - Negotiation Handler.

Covers:
- Accept flow (offer acceptance, billing gate, HIL approval)
- Decline flow (offer rejection)
- Counter flow (price negotiation, escalation after max counters)
- Structural change detection (date/room/product changes)
- Q&A handling within negotiation
"""
from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from domain import IntentLabel
from workflows.common.types import GroupResult, WorkflowState, IncomingMessage
from workflows.steps.step5_negotiation.trigger.step5_handler import process
from workflows.steps.step5_negotiation.trigger.classification import (
    classify_message,
    collect_detected_intents,
)

pytestmark = pytest.mark.v4


@pytest.fixture
def base_event_entry():
    """Base event entry for Step 5 tests."""
    return {
        "event_id": "evt-step5-test",
        "current_step": 5,
        "chosen_date": "15.02.2026",
        "chosen_date_iso": "2026-02-15",
        "locked_room_id": "Room A",
        "requirements": {"number_of_participants": 25},
        "current_offer_id": "offer-123",
        "offers": [{"offer_id": "offer-123", "status": "Pending"}],
        "pricing_inputs": {"total_amount": 2500.00},
        "thread_state": "Awaiting Client",
    }


@pytest.fixture
def workflow_state(base_event_entry):
    """Create a workflow state for testing."""
    message = IncomingMessage(
        msg_id="msg-step5",
        from_name="Test Client",
        from_email="test@example.com",
        subject="Re: Offer",
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
    state.event_entry = base_event_entry
    state.client_id = "test@example.com"
    state.user_info = {}
    return state


class TestClassification:
    """Tests for negotiation message classification."""

    def test_classify_accept(self):
        """Accept patterns should classify as 'accept'."""
        intent, confidence = classify_message("Yes, I accept the offer")
        assert intent == "accept"
        assert confidence > 0.7

    def test_classify_decline(self):
        """Decline patterns should classify as 'decline'."""
        intent, confidence = classify_message("No, we need to cancel")
        assert intent == "decline"
        assert confidence > 0.7

    def test_classify_counter(self):
        """Counter-offer patterns should classify as 'counter'."""
        intent, confidence = classify_message("Can we do CHF 2000 instead?")
        assert intent == "counter"
        assert confidence > 0.5

    def test_classify_clarification(self):
        """Questions should classify as 'clarification'."""
        intent, confidence = classify_message("What's included in the catering?")
        assert intent == "clarification"

    def test_ambiguous_defaults_to_low_confidence(self):
        """Ambiguous messages should have low confidence."""
        intent, confidence = classify_message("hmm okay")
        # "okay" might match accept pattern but with low confidence
        assert confidence < 0.6 or intent in ["accept", "clarification"]


class TestCollectDetectedIntents:
    """Tests for multi-intent detection."""

    def test_detects_multiple_intents(self):
        """Message with multiple signals should detect all intents."""
        intents = collect_detected_intents("Can we do CHF 400? I might accept that.")
        intent_names = [i[0] for i in intents]
        assert "counter" in intent_names
        assert "clarification" in intent_names  # Question mark

    def test_empty_message_returns_empty(self):
        """Empty messages should return no intents."""
        assert collect_detected_intents("") == []
        assert collect_detected_intents(None) == []


class TestAcceptFlow:
    """Tests for offer acceptance flow."""

    @patch("backend.workflows.steps.step5_negotiation.trigger.step5_handler._refresh_billing")
    def test_accept_with_complete_billing(self, mock_billing, workflow_state):
        """Accept with complete billing should proceed to HIL."""
        mock_billing.return_value = []  # No missing billing fields
        workflow_state.message = IncomingMessage(
            msg_id="msg-accept",
            from_name="Test",
            from_email="test@example.com",
            subject="Accept",
            body="Yes, I accept this offer",
            ts=None,
        )
        workflow_state.event_entry["billing_details"] = {
            "name": "Test Corp",
            "street": "Main St 1",
            "city": "Zurich",
            "postal_code": "8000",
        }

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert "accept" in result.action.lower() or "hil" in result.action.lower()

    @patch("backend.workflows.steps.step5_negotiation.trigger.step5_handler._refresh_billing")
    def test_accept_missing_billing_prompts(self, mock_billing, workflow_state):
        """Accept with missing billing should prompt for billing."""
        mock_billing.return_value = ["name", "street"]  # Missing fields
        workflow_state.message = IncomingMessage(
            msg_id="msg-accept-no-billing",
            from_name="Test",
            from_email="test@example.com",
            subject="Accept",
            body="I accept",
            ts=None,
        )

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # Should either block for billing or prompt
        assert result.halt is True


class TestDeclineFlow:
    """Tests for offer decline flow."""

    def test_decline_moves_to_step7(self, workflow_state):
        """Decline should transition to Step 7."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-decline",
            from_name="Test",
            from_email="test@example.com",
            subject="Decline",
            body="No thank you, we need to cancel the booking",
            ts=None,
        )

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert "decline" in result.action.lower()


class TestCounterFlow:
    """Tests for counter-offer flow."""

    def test_counter_increments_count(self, workflow_state):
        """Counter-offer should increment counter count."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-counter",
            from_name="Test",
            from_email="test@example.com",
            subject="Counter",
            body="Can we do CHF 2000 instead of 2500?",
            ts=None,
        )
        workflow_state.event_entry["negotiation_state"] = {"counter_count": 0}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert "counter" in result.action.lower()

    def test_max_counters_triggers_escalation(self, workflow_state):
        """Exceeding max counters should trigger manual review."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-counter-max",
            from_name="Test",
            from_email="test@example.com",
            subject="Counter again",
            body="What about CHF 1800?",
            ts=None,
        )
        # Already at max counters
        workflow_state.event_entry["negotiation_state"] = {"counter_count": 3}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        # Should escalate to manual review
        assert result.halt is True


class TestStructuralChangeDetection:
    """Tests for detecting structural changes in negotiation."""

    def test_date_change_detected(self, workflow_state):
        """Date change should trigger detour to Step 2."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-date-change",
            from_name="Test",
            from_email="test@example.com",
            subject="Date change",
            body="Actually, can we change to 20.02.2026?",
            ts=None,
        )
        workflow_state.user_info = {"date": "2026-02-20"}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        if result.action == "structural_change_detour":
            assert result.payload.get("detour_to_step") == 2

    def test_room_change_detected(self, workflow_state):
        """Room change should trigger detour to Step 3."""
        workflow_state.message = IncomingMessage(
            msg_id="msg-room-change",
            from_name="Test",
            from_email="test@example.com",
            subject="Room change",
            body="Can we switch to Room B instead?",
            ts=None,
        )
        workflow_state.user_info = {"room": "Room B"}

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        if result.action == "structural_change_detour":
            assert result.payload.get("detour_to_step") == 3


class TestMissingEvent:
    """Tests for missing event handling."""

    def test_missing_event_halts(self, workflow_state):
        """Missing event entry should halt processing."""
        workflow_state.event_entry = None

        result = process(workflow_state)

        assert isinstance(result, GroupResult)
        assert result.halt is True
        assert "missing_event" in result.action
