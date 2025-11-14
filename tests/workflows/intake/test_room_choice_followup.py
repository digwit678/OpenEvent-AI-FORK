from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, db: dict, message: IncomingMessage) -> WorkflowState:
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-room-choice"
    return state


def test_room_choice_reply_routes_without_manual_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")

    # Force classifier to downgrade confidence so heuristics kick in.
    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(
        intake_module,
        "extract_user_information",
        lambda _payload: {
            "room": None,
            "event_date": "07.02.2026",
        },
    )

    captured_args: dict[str, tuple[str, str, str | None]] = {}

    def _fake_room_selection(state: WorkflowState, *, room: str, status: str, date: str | None = None):
        captured_args["room"] = (room, status, date)
        from backend.workflows.common.types import GroupResult

        return GroupResult(action="room_selected", payload={"room": room, "status": status}, halt=False)

    monkeypatch.setattr(intake_module, "handle_select_room_action", _fake_room_selection)

    existing_event = {
        "event_id": "EVT-ROOM",
        "client_id": "laura@example.com",
        "current_step": 3,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
        "chosen_date": "07.02.2026",
        "requirements": {"number_of_participants": 30},
        "room_pending_decision": {
            "selected_room": "Room A",
            "selected_status": "Available",
        },
        "event_data": {"Email": "laura@example.com"},
    }
    db = {
        "events": [existing_event],
        "clients": {
            "laura@example.com": {
                "profile": {"name": None, "org": None, "phone": None},
                "history": [],
                "event_ids": [existing_event["event_id"]],
            }
        },
        "tasks": [],
    }

    message = IncomingMessage(
        msg_id="msg-room-choice",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Re: Private Dinner Event – Date Options in February",
        body="Room A",
        ts="2025-11-14T01:40:00Z",
    )

    state = _state(tmp_path, db, message)
    intake_module.process(state)

    assert captured_args, "Room selection handler should be invoked"
    assert captured_args["room"][0] == "Room A"
    assert captured_args["room"][1] == "Available"
    assert captured_args["room"][2] == "07.02.2026"
