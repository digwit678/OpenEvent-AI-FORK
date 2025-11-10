from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

import importlib

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")
room_process = room_module.process
handle_select_room_action = room_module.handle_select_room_action


def _build_state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-select-room",
        from_name="Client",
        from_email="client@example.com",
        subject=None,
        body="Room A looks good.",
        ts="2025-12-02T09:15:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_id = "EVT-SELECT"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    return state


def _seed_event(state: WorkflowState) -> None:
    requirements = {"number_of_participants": 36, "seating_layout": "banquet"}
    req_hash = requirements_hash(requirements)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "2026-03-10",
        "date_confirmed": True,
        "thread_state": "Awaiting Client",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
    }


def test_room_marked_selected_only_after_action(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    state = _build_state(tmp_path)
    _seed_event(state)

    monkeypatch.setattr(
        room_module,
        "evaluate_room_statuses",
        lambda _db, _date: [{"Room A": "Available"}, {"Room B": "Option"}],
    )
    monkeypatch.setattr(
        room_module,
        "_needs_better_room_alternatives",
        lambda *_args, **_kwargs: False,
    )

    room_process(state)
    assert state.event_entry
    assert state.event_entry.get("selected_room") is None

    calls: List[Tuple[str, str, str]] = []

    def fake_update(db: Dict[str, Any], event_id: str, *, selected_room: str, status: str) -> Dict[str, Any]:
        calls.append((event_id, selected_room, status))
        state.event_entry["selected_room"] = selected_room
        state.event_entry["selected_room_status"] = status
        return state.event_entry

    monkeypatch.setattr(room_module, "update_event_room", fake_update)

    state.draft_messages.clear()
    result = handle_select_room_action(state, room="Room A", status="Option", date="2026-03-10")

    assert result.action == "room_selected"
    assert calls == [("EVT-SELECT", "Room A", "Option")]
    assert state.event_entry.get("selected_room") == "Room A"
    assert getattr(state, "flags", {}).get("room_selected") is True
    assert state.draft_messages, "Follow-up draft should be queued"
    follow_up = state.draft_messages[-1]
    assert "Great — Room A on" in follow_up["body"]
    assert any(action.get("type") == "explore_products" for action in follow_up["actions"])
    assert any(action.get("type") == "confirm_products" for action in follow_up["actions"])
