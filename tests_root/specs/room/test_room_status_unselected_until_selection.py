from __future__ import annotations

from debug.hooks import clear_subloop, trace_state
from debug.trace import BUS


def test_room_status_transitions(monkeypatch):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    BUS._buf.clear()  # type: ignore[attr-defined]
    thread_id = "room-status-thread"

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "date_confirmed": True,
            "requirements_hash": "hash-1",
            "room_eval_hash": "hash-1",
        },
    )
    events = BUS.get(thread_id)  # type: ignore[attr-defined]
    first_snapshot = next(
        event for event in events if event.get("kind") == "STATE_SNAPSHOT" and event.get("owner_step") == "Step3_Room"
    )
    first_data = first_snapshot.get("data") or {}
    assert first_data.get("room_status") == "Unselected"
    counters = first_data.get("step_counters", {}).get("Step3_Room", {})
    if counters:
        assert counters.get("met", 0) <= 2
    clear_subloop(thread_id)

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "date_confirmed": True,
            "locked_room_id": "Room A",
            "locked_room_status": "Available",
            "requirements_hash": "hash-1",
            "room_eval_hash": "hash-1",
        },
    )
    events = BUS.get(thread_id)  # type: ignore[attr-defined]
    latest_snapshot = [event for event in events if event.get("kind") == "STATE_SNAPSHOT" and event.get("owner_step") == "Step3_Room"][-1]
    latest_data = latest_snapshot.get("data") or {}
    assert latest_data.get("room_status") == "Available"
    assert latest_data.get("requirements_match") is True
    counters = latest_data.get("step_counters", {}).get("Step3_Room", {})
    if counters:
        assert counters.get("met") == counters.get("total") == 3

    BUS._buf.clear()  # type: ignore[attr-defined]
