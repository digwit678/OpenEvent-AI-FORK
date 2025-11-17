from __future__ import annotations

import importlib
from pathlib import Path

from backend.workflows.common.types import IncomingMessage, WorkflowState


def _build_state(tmp_path: Path) -> WorkflowState:
    db = {"events": [], "clients": {}, "tasks": []}
    message = IncomingMessage(
        msg_id="msg-confirm",
        from_name="Patrick Keller",
        from_email="patrick.keller@example.com",
        subject="Re: Client Appreciation Event – Date options",
        body="2027-03-12 18:00-22:00",
        ts="2026-11-17T20:45:00Z",
    )
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-confirm"
    return state


def test_resolve_confirmation_window_recovers_from_inverted_times(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    state = _build_state(tmp_path)
    state.user_info["date"] = "2027-03-12"
    state.user_info["start_time"] = "18:00"
    state.user_info["end_time"] = "03:00"

    event_entry = {
        "event_id": "EVT-123",
        "requirements": {},
        "event_data": {},
    }

    window = module._resolve_confirmation_window(state, event_entry)

    assert window is not None
    assert window.start_time == "18:00"
    assert window.end_time == "22:00"
    assert window.partial is False
    assert state.user_info["end_time"] == "22:00"
