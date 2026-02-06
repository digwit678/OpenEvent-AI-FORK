"""Unit tests for delete_event() hard-delete function."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from workflows.io.database import (
    delete_event,
    find_event_idx_by_id,
    get_event_dates,
    get_default_db,
)


def _make_db_with_event(event_id="evt-1", email="client@example.com", date="15.03.2026"):
    """Create a minimal database with one event and related records."""
    db = get_default_db()
    db["events"].append({
        "event_id": event_id,
        "status": "Lead",
        "current_step": 3,
        "chosen_date": date,
        "locked_room_id": "Room A",
        "event_data": {
            "Email": email,
            "Event Date": date,
            "Name": "Test Client",
        },
        "deposit_state": {"status": "not_required"},
    })
    db["clients"][email.lower()] = {
        "profile": {"name": "Test Client"},
        "event_ids": [event_id],
    }
    db["email_messages"].append({
        "msg_id": "msg-1",
        "resolved_event_id": event_id,
        "body": "test",
    })
    db["email_messages"].append({
        "msg_id": "msg-2",
        "resolved_event_id": "other-event",
        "body": "other",
    })
    db["event_signatures"].append({
        "event_id": event_id,
        "signature": "abc",
    })
    db["thread_mappings"].append({
        "thread_id": "thread-1",
        "event_id": event_id,
    })
    db["thread_mappings"].append({
        "thread_id": "thread-2",
        "event_id": "other-event",
    })
    return db


class TestDeleteEvent:
    """Tests for delete_event() hard-delete."""

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_deletes_event_from_db(self, mock_snapshots):
        db = _make_db_with_event()
        assert find_event_idx_by_id(db, "evt-1") is not None

        summary = delete_event(db, "evt-1")

        assert find_event_idx_by_id(db, "evt-1") is None
        assert summary["event_id"] == "evt-1"
        assert summary["client_email"] == "client@example.com"

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_cleans_up_email_messages(self, mock_snapshots):
        db = _make_db_with_event()
        assert len(db["email_messages"]) == 2

        delete_event(db, "evt-1")

        # Only the non-related message should remain
        assert len(db["email_messages"]) == 1
        assert db["email_messages"][0]["resolved_event_id"] == "other-event"

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_cleans_up_event_signatures(self, mock_snapshots):
        db = _make_db_with_event()
        assert len(db["event_signatures"]) == 1

        delete_event(db, "evt-1")

        assert len(db["event_signatures"]) == 0

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_cleans_up_thread_mappings(self, mock_snapshots):
        db = _make_db_with_event()
        assert len(db["thread_mappings"]) == 2

        delete_event(db, "evt-1")

        assert len(db["thread_mappings"]) == 1
        assert db["thread_mappings"][0]["event_id"] == "other-event"

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_removes_from_client_event_ids(self, mock_snapshots):
        db = _make_db_with_event()
        assert "evt-1" in db["clients"]["client@example.com"]["event_ids"]

        delete_event(db, "evt-1")

        assert "evt-1" not in db["clients"]["client@example.com"]["event_ids"]

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_calls_delete_snapshots(self, mock_snapshots):
        db = _make_db_with_event()

        delete_event(db, "evt-1")

        mock_snapshots.assert_called_once_with("evt-1")

    @patch("utils.page_snapshots.delete_snapshots_for_event", side_effect=Exception("snap fail"))
    def test_snapshot_failure_does_not_raise(self, mock_snapshots):
        """Snapshot deletion is best-effort — should not propagate errors."""
        db = _make_db_with_event()

        summary = delete_event(db, "evt-1")

        assert summary["event_id"] == "evt-1"
        assert find_event_idx_by_id(db, "evt-1") is None

    def test_raises_for_unknown_event_id(self):
        db = get_default_db()

        with pytest.raises(ValueError, match="not found"):
            delete_event(db, "nonexistent")

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_date_room_freed_after_deletion(self, mock_snapshots):
        """After deletion, get_event_dates() should not find the deleted event's date."""
        db = _make_db_with_event(date="15.03.2026")
        dates_before = get_event_dates(db)
        assert "2026-03-15" in dates_before

        delete_event(db, "evt-1")

        dates_after = get_event_dates(db)
        assert "2026-03-15" not in dates_after

    @patch("utils.page_snapshots.delete_snapshots_for_event")
    def test_returns_summary_with_metadata(self, mock_snapshots):
        db = _make_db_with_event()

        summary = delete_event(db, "evt-1")

        assert summary["event_id"] == "evt-1"
        assert summary["client_email"] == "client@example.com"
        assert summary["chosen_date"] == "15.03.2026"
        assert summary["locked_room_id"] == "Room A"
        assert summary["step"] == 3
        assert summary["status"] == "Lead"
