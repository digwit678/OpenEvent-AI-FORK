from __future__ import annotations

from pathlib import Path

from workflows.common.types import IncomingMessage, WorkflowState
from workflows.planner.smart_shortcuts import maybe_run_smart_shortcuts, _shortcuts_allowed


def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="shortcut-guard",
        from_name="Client",
        from_email="client@example.com",
        subject=None,
        body=None,
        ts=None,
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "shortcuts.json", db={"events": []})
    state.event_id = "EVT-GATE"
    return state


def test_shortcuts_block_without_confirmed_date(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    state = _state(tmp_path)
    event_entry = {
        "event_id": state.event_id,
        "current_step": 3,
        "date_confirmed": False,
        "requirements": {"number_of_participants": None},
        "shortcuts": {},
    }
    state.event_entry = event_entry
    state.current_step = 3

    assert maybe_run_smart_shortcuts(state) is None


def test_shortcuts_block_without_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    state = _state(tmp_path)
    event_entry = {
        "event_id": state.event_id,
        "current_step": 3,
        "date_confirmed": True,
        "requirements": {"number_of_participants": None},
        "shortcuts": {},
    }
    state.event_entry = event_entry
    state.current_step = 3

    assert maybe_run_smart_shortcuts(state) is None


def test_shortcuts_allowed_with_participants():
    event_entry = {
        "event_id": "EVT-GATE",
        "current_step": 3,
        "date_confirmed": True,
        "requirements": {"number_of_participants": 42},
        "shortcuts": {},
    }
    assert _shortcuts_allowed(event_entry) is True