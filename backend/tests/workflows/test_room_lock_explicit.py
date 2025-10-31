from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.groups.room_availability.trigger.process import process
from backend.workflows.io.database import ensure_event_defaults


def _build_message(body: str) -> IncomingMessage:
    return IncomingMessage(
        msg_id="msg-explicit",
        from_name="Taylor Client",
        from_email="taylor@example.com",
        subject="Workshop booking",
        body=body,
        ts="2025-01-01T12:00:00Z",
    )


def test_explicit_lock_bypasses_auto_lock_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALLOW_AUTO_ROOM_LOCK", "false")

    event_entry = {
        "event_id": "evt-explicit",
        "client_id": "client-explicit",
        "chosen_date": "02.11.2025",
        "requested_window": {"date_iso": "2025-11-02", "display_date": "02.11.2025"},
        "requirements": {"number_of_participants": 15},
        "requirements_hash": None,
        "room_eval_hash": None,
        "date_confirmed": True,
    }
    ensure_event_defaults(event_entry)
    event_entry["current_step"] = 3

    db = {"events": [event_entry]}
    message = _build_message("Please lock Room B for us.")
    state = WorkflowState(message=message, db_path=tmp_path / "db.json", db=db)
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.client_id = event_entry["client_id"]
    state.client = {"email": "taylor@example.com"}
    state.intent = IntentLabel.EVENT_REQUEST
    state.confidence = 0.95

    result = process(state)

    assert result.action == "room_auto_locked"
    assert state.event_entry.get("locked_room_id") == "Room B"
    decision = state.event_entry.get("room_decision") or {}
    assert decision.get("status") == "locked"
    assert decision.get("reason") == "explicit_lock"
