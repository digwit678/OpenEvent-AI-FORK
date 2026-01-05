"""
Test that direct client room selection (via handle_select_room_action)
properly locks the room and advances to Step 4 (Offer).

This test verifies the fix for the bug where selecting a room would loop
back to Step 3 instead of advancing to Step 4.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.step3_handler")
selection_module = importlib.import_module("backend.workflows.steps.step3_room_availability.trigger.selection")
handle_select_room_action = room_module.handle_select_room_action


def test_room_selection_sets_locked_room_and_advances_to_step4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """
    When client selects a room directly (not via HIL approval),
    the workflow should:
    1. Set locked_room_id
    2. Set room_eval_hash to current requirements_hash
    3. Advance to Step 4 (current_step=4)
    4. Not loop back to Step 3
    """
    msg = IncomingMessage(
        msg_id="msg-select",
        from_name="Client",
        from_email="client@example.com",
        subject=None,
        body="I'll take Room B",
        ts="2025-12-02T10:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_id = "EVT-STEP4-TEST"
    state.current_step = 3

    requirements = {"number_of_participants": 30, "seating_layout": "banquet"}
    req_hash = requirements_hash(requirements)

    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "2026-02-07",
        "date_confirmed": True,
        "requirements": requirements,
        "requirements_hash": req_hash,
        "room_eval_hash": None,
        "locked_room_id": None,
        "thread_state": "Awaiting Client",
    }

    # Mock update_event_room to track calls
    def fake_update_room(db, event_id, *, selected_room: str, status: str):
        state.event_entry["selected_room"] = selected_room
        state.event_entry["selected_room_status"] = status
        return state.event_entry

    monkeypatch.setattr(selection_module, "update_event_room", fake_update_room)

    # Execute room selection
    result = handle_select_room_action(state, room="Room B", status="Available", date="2026-02-07")

    # Assertions
    assert result.action == "room_selected", "Action should indicate room was selected"

    # CRITICAL: Verify locked_room_id is set (this was the bug)
    assert state.event_entry.get("locked_room_id") == "Room B", (
        "locked_room_id should be set to prevent Step 3 from re-running"
    )

    # CRITICAL: Verify room_eval_hash is set
    assert state.event_entry.get("room_eval_hash") == req_hash, (
        "room_eval_hash should match requirements_hash to capture the snapshot"
    )

    # CRITICAL: Verify advancement to Step 4 (this was the bug)
    assert state.current_step == 4, "Workflow should advance to Step 4 (Offer)"
    assert state.event_entry.get("current_step") == 4, "Event metadata should reflect Step 4"

    # Verify other expected behavior
    assert state.event_entry.get("selected_room") == "Room B"
    assert state.draft_messages, "Should queue follow-up message"

    follow_up = state.draft_messages[-1]
    assert follow_up["step"] == 4, "Message footer should indicate Step 4"
    assert "Room B" in follow_up["body"]
    assert "reserved as an option" in follow_up["body"]


def test_room_selection_prevents_step3_reentry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """
    After room selection, when the workflow re-enters Step 3 gate checks,
    it should skip Step 3 because locked_room_id is set.

    This verifies the fix prevents the infinite loop.
    """
    msg = IncomingMessage(
        msg_id="msg-after-room",
        from_name="Client",
        from_email="client@example.com",
        subject=None,
        body="I'd like to add some wine",
        ts="2025-12-02T11:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_id = "EVT-NO-LOOP"
    state.current_step = 4

    requirements = {"number_of_participants": 30, "seating_layout": "banquet"}
    req_hash = requirements_hash(requirements)

    # State AFTER room selection (with locked_room_id set)
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "2026-02-07",
        "date_confirmed": True,
        "requirements": requirements,
        "requirements_hash": req_hash,
        "locked_room_id": "Room B",  # ← Room is locked
        "room_eval_hash": req_hash,  # ← Hash matches
        "selected_room": "Room B",
        "selected_room_status": "Available",
        "current_step": 4,  # ← Already at Step 4
        "thread_state": "Awaiting Client",
    }

    monkeypatch.setattr(
        room_module,
        "evaluate_room_statuses",
        lambda _db, _date: [{"Room B": "Available"}],
    )
    monkeypatch.setattr(
        room_module,
        "_needs_better_room_alternatives",
        lambda *_: False,
    )

    # Try to process Step 3 again (should skip)
    room_process = room_module.process
    result = room_process(state)

    # Should skip Step 3 evaluation since room is locked
    assert result.action != "room_avail_result", (
        "Step 3 should be skipped when locked_room_id is already set"
    )
