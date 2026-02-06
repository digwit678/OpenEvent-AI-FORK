"""Integration tests for the complete cancellation flow.

Tests the full pipeline: detection → handler → hard-delete → response,
ensuring correct routing for cancellation vs partial cancels vs Q&A.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from detection.unified import UnifiedDetectionResult
from workflows.common.cancellation_handler import (
    handle_cancellation,
    is_cancellation_intent,
)
from workflows.io.database import (
    delete_event,
    find_event_idx_by_id,
    get_default_db,
    get_event_dates,
)


def _make_test_state(event_id="evt-1", email="client@test.com", step=3):
    """Create a minimal WorkflowState-like object for testing."""
    from workflows.common.types import WorkflowState, IncomingMessage
    from pathlib import Path

    db = get_default_db()
    db["events"].append({
        "event_id": event_id,
        "status": "Lead",
        "current_step": step,
        "chosen_date": "15.03.2026",
        "locked_room_id": "Room A",
        "event_data": {
            "Email": email,
            "Event Date": "15.03.2026",
            "Name": "Test Client",
        },
        "deposit_state": {"status": "not_required"},
    })
    db["clients"][email.lower()] = {
        "profile": {"name": "Test"},
        "event_ids": [event_id],
    }

    msg = IncomingMessage(
        msg_id="msg-1",
        from_name="Test",
        from_email=email,
        subject="Cancel",
        body="Please cancel our event",
        ts="2026-01-01T00:00:00Z",
    )

    state = WorkflowState(
        message=msg,
        db_path=Path("/tmp/test_db.json"),
        db=db,
        client_id=email,
        thread_id="thread-1",
        event_entry=db["events"][0],
    )
    return state, db


class TestCancellationFlowIntegration:
    """Integration tests for the full cancellation pipeline."""

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    @patch("workflows.io.tasks.enqueue_task", return_value="task-1")
    @patch("workflows.io.database.save_db")
    @patch("workflows.io.database.lock_path_for")
    def test_full_cancellation_deletes_event(
        self, mock_lock, mock_save, mock_task, mock_snap
    ):
        """'Please cancel our event' at step 3 → event DELETED, farewell returned."""
        state, db = _make_test_state(step=3)
        detection = UnifiedDetectionResult(is_cancellation=True)

        result = handle_cancellation(state, state.event_entry, detection)

        # Event should be deleted from DB
        assert find_event_idx_by_id(db, "evt-1") is None
        # Date/room freed
        assert "2026-03-15" not in get_event_dates(db)
        # Result indicates halt
        assert result.halt is True
        assert result.action == "event_cancelled_deleted"
        # State cleared
        assert state.event_entry is None
        # HIL task was created
        mock_task.assert_called_once()

    def test_site_visit_cancel_not_full_cancel(self):
        """'Cancel the site visit' → NOT a full cancel."""
        detection = UnifiedDetectionResult(
            is_site_visit_change=True,
            is_cancellation=False,
        )
        assert is_cancellation_intent(detection, "cancel the site visit") is False

    def test_room_change_not_full_cancel(self):
        """'Cancel room B, we want room A' → NOT a full cancel."""
        detection = UnifiedDetectionResult(
            is_change_request=True,
            is_cancellation=False,
        )
        assert is_cancellation_intent(detection, "Cancel room B, we want room A") is False

    def test_qna_cancellation_policy_not_cancel(self):
        """'What's the cancellation fee?' → NOT cancelled, Q&A response."""
        detection = UnifiedDetectionResult(
            is_question=True,
            is_cancellation=False,
        )
        assert is_cancellation_intent(detection, "What's the cancellation fee?") is False

    def test_cancel_everything_is_full_cancel(self):
        """'We need to cancel everything' → full cancel."""
        detection = UnifiedDetectionResult(is_cancellation=True)
        assert is_cancellation_intent(detection, "We need to cancel everything") is True

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    @patch("workflows.io.tasks.enqueue_task", return_value="task-1")
    @patch("workflows.io.database.save_db")
    @patch("workflows.io.database.lock_path_for")
    def test_deposit_paid_noted_in_response(
        self, mock_lock, mock_save, mock_task, mock_snap
    ):
        """When deposit was paid, farewell message mentions refund follow-up."""
        state, db = _make_test_state()
        state.event_entry["deposit_state"] = {"status": "paid", "due_amount": 500.0}
        detection = UnifiedDetectionResult(is_cancellation=True)

        result = handle_cancellation(state, state.event_entry, detection)

        assert result.payload["deposit_paid"] is True
        # Check draft message mentions refund
        drafts = state.draft_messages
        assert any("refund" in d.get("body", "").lower() for d in drafts)

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_manager_cancel_api_hard_deletes(self, mock_snap):
        """Manager cancel via API → event hard-deleted, not just status change."""
        db = get_default_db()
        db["events"].append({
            "event_id": "evt-api",
            "status": "Lead",
            "current_step": 4,
            "chosen_date": "20.04.2026",
            "locked_room_id": "Room B",
            "event_data": {"Email": "api@test.com", "Event Date": "20.04.2026"},
        })
        db["clients"]["api@test.com"] = {
            "profile": {"name": "API Client"},
            "event_ids": ["evt-api"],
        }

        summary = delete_event(db, "evt-api")

        assert find_event_idx_by_id(db, "evt-api") is None
        assert summary["event_id"] == "evt-api"
        assert "evt-api" not in db["clients"]["api@test.com"]["event_ids"]
