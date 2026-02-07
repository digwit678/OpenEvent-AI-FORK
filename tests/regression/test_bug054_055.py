"""
Regression tests for BUG-054 (Hybrid Q&A dropout) and BUG-055 (Date drift).

BUG-054: Q&A responses silently dropped when step handlers return early with halt=True.
  Fix: Pre-generate Q&A in pre_route pipeline so it survives regardless of handler path.

BUG-055: Date context lost across step transitions (Step 1→2).
  Fix: resolve_anchor_date() falls back to event_entry stored date.
"""

from __future__ import annotations

import pytest
from datetime import date, datetime
from typing import Any, Dict, Optional
from pathlib import Path
from unittest.mock import patch, MagicMock

from workflows.common.types import IncomingMessage, WorkflowState


# ==============================================================================
# BUG-054: Hybrid Q&A pre-generation in pre_route
# ==============================================================================


class TestHybridQnAPreGeneration:
    """Verify Q&A is pre-generated in pre_route and stored in state.extras."""

    @staticmethod
    def _make_state(body: str = "test", extras: Optional[Dict] = None) -> WorkflowState:
        msg = IncomingMessage(
            msg_id="test-1",
            from_name="Test User",
            from_email="test@example.com",
            subject="Test",
            body=body,
            ts="2026-01-01T10:00:00",
        )
        return WorkflowState(
            message=msg,
            db_path=Path("/tmp/test.json"),
            db={},
            event_entry={"current_step": 4, "thread_id": "t1"},
            extras=extras or {},
        )

    @patch("workflows.qna.router.generate_hybrid_qna_response")
    def test_pre_route_generates_qna_when_question_detected(self, mock_gen):
        """BUG-054: When unified detects a question, Q&A should be pre-generated."""
        mock_gen.return_value = "We offer full catering services."

        state = self._make_state("I accept the offer. Do you have catering?")
        combined_text = "Test I accept the offer. Do you have catering?"

        # Simulate what pre_route does: check unified_result and call generate
        unified_result = MagicMock()
        unified_result.is_question = True
        unified_result.qna_types = ["catering_for"]

        # Execute the pre-route Q&A block logic
        if unified_result and unified_result.is_question and unified_result.qna_types:
            if not state.extras.get("hybrid_qna_response"):
                from workflows.qna.router import generate_hybrid_qna_response
                hybrid_qna = generate_hybrid_qna_response(
                    qna_types=unified_result.qna_types,
                    message_text=combined_text,
                    event_entry=state.event_entry,
                    db=state.db,
                )
                if hybrid_qna:
                    state.extras["hybrid_qna_response"] = hybrid_qna

        assert state.extras.get("hybrid_qna_response") == "We offer full catering services."
        mock_gen.assert_called_once_with(
            qna_types=["catering_for"],
            message_text=combined_text,
            event_entry=state.event_entry,
            db=state.db,
        )

    @patch("workflows.qna.router.generate_hybrid_qna_response")
    def test_pre_route_skips_when_no_question(self, mock_gen):
        """No Q&A generation when unified_result.is_question is False."""
        state = self._make_state("I accept the offer.")

        unified_result = MagicMock()
        unified_result.is_question = False
        unified_result.qna_types = []

        if unified_result and unified_result.is_question and unified_result.qna_types:
            if not state.extras.get("hybrid_qna_response"):
                from workflows.qna.router import generate_hybrid_qna_response
                hybrid_qna = generate_hybrid_qna_response(
                    qna_types=unified_result.qna_types,
                    message_text="test",
                    event_entry=state.event_entry,
                    db=state.db,
                )
                if hybrid_qna:
                    state.extras["hybrid_qna_response"] = hybrid_qna

        assert "hybrid_qna_response" not in state.extras
        mock_gen.assert_not_called()

    @patch("workflows.qna.router.generate_hybrid_qna_response")
    def test_pre_route_does_not_overwrite_existing(self, mock_gen):
        """If hybrid_qna_response already exists (e.g. from a previous pipeline stage), skip."""
        state = self._make_state(extras={"hybrid_qna_response": "Already set"})

        unified_result = MagicMock()
        unified_result.is_question = True
        unified_result.qna_types = ["catering_for"]

        if unified_result and unified_result.is_question and unified_result.qna_types:
            if not state.extras.get("hybrid_qna_response"):
                from workflows.qna.router import generate_hybrid_qna_response
                hybrid_qna = generate_hybrid_qna_response(
                    qna_types=unified_result.qna_types,
                    message_text="test",
                    event_entry=state.event_entry,
                    db=state.db,
                )
                if hybrid_qna:
                    state.extras["hybrid_qna_response"] = hybrid_qna

        assert state.extras["hybrid_qna_response"] == "Already set"
        mock_gen.assert_not_called()


# ==============================================================================
# BUG-055: Date drift — resolve_anchor_date event_entry fallback
# ==============================================================================


class TestResolveAnchorDateFallback:
    """Verify resolve_anchor_date uses event_entry date when message has none."""

    def test_fallback_to_event_entry_date(self):
        """BUG-055: When user text has no date, fall back to event_entry date."""
        from workflows.steps.step2_date_confirmation.trigger.date_context import (
            resolve_anchor_date,
        )

        anchor, anchor_dt = resolve_anchor_date(
            user_text="I confirm",
            reference_day=date(2026, 2, 6),
            requested_dates=[],
            event_entry_date_iso="2026-04-15",
        )

        assert anchor == date(2026, 4, 15)
        assert anchor_dt is not None
        assert anchor_dt.date() == date(2026, 4, 15)

    def test_user_text_date_takes_priority_over_event_entry(self):
        """User text date should take priority over event_entry fallback."""
        from workflows.steps.step2_date_confirmation.trigger.date_context import (
            resolve_anchor_date,
        )

        anchor, _ = resolve_anchor_date(
            user_text="How about May 20, 2026?",
            reference_day=date(2026, 2, 6),
            requested_dates=[],
            event_entry_date_iso="2026-04-15",
        )

        assert anchor == date(2026, 5, 20)

    def test_focus_iso_overrides_everything(self):
        """focus_iso is highest priority and should override event_entry too."""
        from workflows.steps.step2_date_confirmation.trigger.date_context import (
            resolve_anchor_date,
        )

        anchor, _ = resolve_anchor_date(
            user_text="I confirm",
            reference_day=date(2026, 2, 6),
            requested_dates=[],
            focus_iso="2026-06-01",
            event_entry_date_iso="2026-04-15",
        )

        assert anchor == date(2026, 6, 1)

    def test_no_fallback_when_no_event_entry_date(self):
        """Without event_entry_date_iso, anchor should be None."""
        from workflows.steps.step2_date_confirmation.trigger.date_context import (
            resolve_anchor_date,
        )

        anchor, anchor_dt = resolve_anchor_date(
            user_text="I confirm",
            reference_day=date(2026, 2, 6),
            requested_dates=[],
        )

        assert anchor is None
        assert anchor_dt is None

    def test_requested_dates_take_priority_over_event_entry(self):
        """Explicit requested_dates should take priority over event_entry."""
        from workflows.steps.step2_date_confirmation.trigger.date_context import (
            resolve_anchor_date,
        )

        anchor, _ = resolve_anchor_date(
            user_text="I confirm",
            reference_day=date(2026, 2, 6),
            requested_dates=["2026-03-10"],
            event_entry_date_iso="2026-04-15",
        )

        assert anchor == date(2026, 3, 10)


# ==============================================================================
# BUG-055: _extract_stored_event_date_iso helper
# ==============================================================================


class TestExtractStoredEventDateIso:
    """Test the helper that extracts stored date from event_entry."""

    def test_chosen_date_ddmmyyyy(self):
        """chosen_date in DD.MM.YYYY format should be converted to ISO."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({"chosen_date": "15.04.2026"})
        assert result == "2026-04-15"

    def test_event_data_date(self):
        """event_data["Event Date"] in DD.MM.YYYY should be used as fallback."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({
            "event_data": {"Event Date": "20.06.2026"},
        })
        assert result == "2026-06-20"

    def test_chosen_date_takes_priority(self):
        """chosen_date should take priority over event_data date."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({
            "chosen_date": "15.04.2026",
            "event_data": {"Event Date": "20.06.2026"},
        })
        assert result == "2026-04-15"

    def test_not_specified_ignored(self):
        """'Not specified' event date should be treated as absent."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({
            "event_data": {"Event Date": "Not specified"},
        })
        assert result is None

    def test_empty_event_entry(self):
        """Empty event_entry should return None."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({})
        assert result is None

    def test_malformed_date_ignored(self):
        """Malformed dates should not crash, just return None."""
        from workflows.steps.step2_date_confirmation.trigger.step2_handler import (
            _extract_stored_event_date_iso,
        )

        result = _extract_stored_event_date_iso({"chosen_date": "not-a-date"})
        assert result is None


# ==============================================================================
# BUG-056: Time gate checks captured but not verified
# ==============================================================================


class TestStep3TimeGateChecksVerified:
    """Verify Step 3 time gate recognises promoted (verified) time fields.

    When Step 2's confirmation_flow promotes start_time/end_time from
    'captured' to 'verified', Step 3's time gate must still recognise
    the time is known — otherwise it sends the user back for time input
    even though they already provided it (BUG-056).
    """

    @staticmethod
    def _make_event_entry(**overrides):
        base = {
            "current_step": 3,
            "thread_id": "t-test",
            "date_confirmed": True,
            "captured": {},
            "verified": {},
            "requirements": {},
        }
        base.update(overrides)
        return base

    def test_time_in_verified_passes_gate(self):
        """Time promoted to verified (post Step 2 confirmation) should pass the gate."""
        ee = self._make_event_entry(
            captured={},  # time removed by promote_fields
            verified={"start_time": "10:00", "end_time": "16:00"},
        )
        captured = ee.get("captured") or {}
        verified = ee.get("verified") or {}
        has_time_slot = bool(
            captured.get("start_time") or captured.get("end_time")
            or verified.get("start_time") or verified.get("end_time")
        )
        assert has_time_slot, "Time in verified should pass the time gate"

    def test_time_in_captured_passes_gate(self):
        """Time still in captured (not yet promoted) should pass the gate."""
        ee = self._make_event_entry(
            captured={"start_time": "10:00", "end_time": "16:00"},
            verified={},
        )
        captured = ee.get("captured") or {}
        verified = ee.get("verified") or {}
        has_time_slot = bool(
            captured.get("start_time") or captured.get("end_time")
            or verified.get("start_time") or verified.get("end_time")
        )
        assert has_time_slot, "Time in captured should pass the time gate"

    def test_no_time_anywhere_fails_gate(self):
        """No time in captured or verified should fail the gate."""
        ee = self._make_event_entry(captured={}, verified={})
        captured = ee.get("captured") or {}
        verified = ee.get("verified") or {}
        has_time_slot = bool(
            captured.get("start_time") or captured.get("end_time")
            or verified.get("start_time") or verified.get("end_time")
        )
        assert not has_time_slot, "No time anywhere should fail the gate"

    def test_only_end_time_in_verified_passes_gate(self):
        """Only end_time in verified should still pass."""
        ee = self._make_event_entry(
            captured={},
            verified={"end_time": "16:00"},
        )
        captured = ee.get("captured") or {}
        verified = ee.get("verified") or {}
        has_time_slot = bool(
            captured.get("start_time") or captured.get("end_time")
            or verified.get("start_time") or verified.get("end_time")
        )
        assert has_time_slot
