"""Tests for Layer 2: Thread resolver (LLM-based semantic matching).

These tests verify the LLM-based resolver for new emails
that are not replies.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from workflows.io.email_threading import ThreadResolver
from workflows.io.email_threading.models import ResolutionResult


class TestThreadResolver:
    """Tests for ThreadResolver class."""

    def test_resolve_no_candidates_returns_new_event(self, empty_db):
        """Should return new_event when no existing events for client."""
        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="unknown@example.com",
            email_subject="New booking request",
            email_body="I'd like to book a venue for March 15th.",
            db=empty_db,
        )

        assert result.decision == "new_event"
        assert result.reason == "no_existing_events_for_client"

    def test_resolve_attaches_with_high_confidence(self, multi_event_db, mock_llm):
        """Should attach to event when LLM returns high confidence match."""
        mock_llm["result"] = {
            "decision": "attach",
            "event_id": "evt-001",
            "confidence": 0.95,
            "reason": "Matches March 15 workshop",
        }

        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="Workshop question",
            email_body="Quick question about the March 15th workshop.",
            db=multi_event_db,
        )

        assert result.decision == "attach"
        assert result.event_id == "evt-001"
        assert result.confidence >= 0.85

    def test_resolve_creates_new_for_low_confidence(self, multi_event_db, mock_llm):
        """Should create new event when confidence is below threshold."""
        mock_llm["result"] = {
            "decision": "attach",
            "event_id": "evt-001",
            "confidence": 0.5,  # Below 0.85 threshold
            "reason": "Uncertain match",
        }

        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="Question",
            email_body="Do you have parking?",
            db=multi_event_db,
        )

        assert result.decision == "new_event"
        assert result.reason == "confidence_below_threshold"
        assert "evt-001" in result.possible_duplicates

    def test_resolve_creates_new_when_llm_says_new(self, multi_event_db, mock_llm):
        """Should create new event when LLM indicates new inquiry."""
        mock_llm["result"] = {
            "decision": "new_event",
            "event_id": None,
            "confidence": 0.9,
            "reason": "Different event type and date",
        }

        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="New dinner booking",
            email_body="I'd like to book a dinner for June 20th.",
            db=multi_event_db,
        )

        assert result.decision == "new_event"

    def test_skips_cancelled_events_in_candidates(self, multi_event_db, mock_llm):
        """Should not consider cancelled events as candidates."""
        # Mark evt-001 as cancelled
        multi_event_db["events"][0]["status"] = "Cancelled"

        mock_llm["result"] = {
            "decision": "new_event",
            "confidence": 1.0,
            "reason": "Only cancelled events for client",
        }

        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="Workshop question",
            email_body="Quick question about the workshop.",
            db=multi_event_db,
        )

        # Since evt-001 is cancelled and evt-002 is Confirmed (terminal),
        # there are no valid candidates
        assert result.decision == "new_event"

    def test_validates_event_id_from_llm(self, multi_event_db, mock_llm):
        """Should reject invalid event IDs from LLM."""
        mock_llm["result"] = {
            "decision": "attach",
            "event_id": "evt-nonexistent",  # Invalid ID
            "confidence": 0.95,
            "reason": "Match",
        }

        resolver = ThreadResolver()

        result = resolver.resolve(
            email_from="sarah@corp.com",
            email_subject="Question",
            email_body="Some question.",
            db=multi_event_db,
        )

        assert result.decision == "new_event"
        assert "invalid_event_id" in result.reason.lower()

    def test_handles_llm_json_parsing_error(self, multi_event_db):
        """Should handle malformed LLM response gracefully."""
        # Create a mock that returns invalid JSON
        mock_agent = MagicMock()
        mock_agent.complete.return_value = "Not valid JSON at all"

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            resolver = ThreadResolver()

            result = resolver.resolve(
                email_from="sarah@corp.com",
                email_subject="Question",
                email_body="Some question.",
                db=multi_event_db,
            )

            assert result.decision == "new_event"
            assert "parse_error" in result.reason.lower()

    def test_handles_llm_exception(self, multi_event_db):
        """Should handle LLM exceptions gracefully."""
        mock_agent = MagicMock()
        mock_agent.complete.side_effect = Exception("LLM unavailable")

        with patch("adapters.agent_adapter.get_agent_adapter", return_value=mock_agent):
            resolver = ThreadResolver()

            result = resolver.resolve(
                email_from="sarah@corp.com",
                email_subject="Question",
                email_body="Some question.",
                db=multi_event_db,
            )

            assert result.decision == "new_event"
            assert "llm_error" in result.reason.lower()


class TestCandidateSelection:
    """Tests for candidate event selection."""

    def test_selects_candidates_by_email(self, multi_event_db):
        """Should only select events for the same client email."""
        resolver = ThreadResolver()

        candidates = resolver._select_candidates(
            "sarah@corp.com",
            multi_event_db,
        )

        # Should include evt-001 (Lead) but not evt-002 (Confirmed=terminal)
        # and not evt-003 (different email)
        event_ids = [c["event_id"] for c in candidates]
        assert "evt-001" in event_ids
        assert "evt-002" not in event_ids  # Terminal status
        assert "evt-003" not in event_ids  # Different email

    def test_limits_candidates(self, multi_event_db):
        """Should respect max_candidates limit."""
        # Add more events for sarah
        for i in range(10):
            multi_event_db["events"].append({
                "event_id": f"evt-extra-{i}",
                "status": "Lead",
                "created_at": f"2026-01-{10+i:02d}T10:00:00Z",
                "event_data": {"Email": "sarah@corp.com"},
            })

        resolver = ThreadResolver()

        candidates = resolver._select_candidates(
            "sarah@corp.com",
            multi_event_db,
            max_candidates=3,
        )

        assert len(candidates) <= 3

    def test_sorts_by_recency(self, multi_event_db):
        """Should return most recent events first."""
        # Add an even more recent event
        multi_event_db["events"].append({
            "event_id": "evt-newest",
            "status": "Lead",
            "created_at": "2026-02-01T10:00:00Z",  # Most recent
            "event_data": {"Email": "sarah@corp.com"},
        })

        resolver = ThreadResolver()

        candidates = resolver._select_candidates(
            "sarah@corp.com",
            multi_event_db,
        )

        assert candidates[0]["event_id"] == "evt-newest"


class TestResolutionResult:
    """Tests for ResolutionResult dataclass."""

    def test_valid_decisions(self):
        """Should accept valid decision values."""
        attach = ResolutionResult(decision="attach", event_id="evt-123", confidence=0.9)
        assert attach.decision == "attach"

        new_event = ResolutionResult(decision="new_event", confidence=1.0)
        assert new_event.decision == "new_event"

    def test_invalid_decision_raises(self):
        """Should raise for invalid decision values."""
        with pytest.raises(ValueError, match="Invalid decision"):
            ResolutionResult(decision="maybe", confidence=0.5)

    def test_possible_duplicates_default(self):
        """Should default to empty list for possible_duplicates."""
        result = ResolutionResult(decision="new_event")
        assert result.possible_duplicates == []
