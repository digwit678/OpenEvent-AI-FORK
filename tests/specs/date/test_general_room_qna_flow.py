from __future__ import annotations

from pathlib import Path

from backend.debug.trace import BUS
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.groups.date_confirmation.trigger.process import process


def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-general",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Room availability",
        body="Which rooms are free on Saturday evenings in February for ~30 people?",
        ts="2025-01-05T09:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "general-room.json", db={"events": []})
    state.client_id = "laura@example.com"
    state.thread_id = "room-thread"
    return state


def test_general_room_qna_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    BUS._buf.clear()  # type: ignore[attr-defined]

    state = _state(tmp_path)
    event_entry = {
        "event_id": "EVT-GENERAL",
        "requirements": {"preferred_room": "Room A"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "date_confirmed": False,
    }
    state.event_entry = event_entry
    state.user_info = {}

    free_dates = ["01.02.2026", "08.02.2026", "15.02.2026"]
    import importlib

    step2_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")
    monkeypatch.setattr(step2_module, "list_free_dates", lambda count, db, preferred_room: free_dates[:count])

    result = process(state)

    assert result.action == "general_rooms_qna"
    draft = state.draft_messages[-1]
    assert draft["topic"] == "general_room_qna"
    assert draft["candidate_dates"] == free_dates
    assert "ROOM AVAILABILITY SNAPSHOT" in draft["body"]
    assert "NEXT STEP" in draft["body"]
    assert draft["footer"].endswith("State: Awaiting Client")

    events = BUS.get(state.thread_id)  # type: ignore[attr-defined]
    assert any(event.get("io", {}).get("op") == "db.dates.general_qna" for event in events if event.get("kind") == "DB_READ")
    assert any(event.get("subject") == "QNA_CLASSIFY" for event in events)
