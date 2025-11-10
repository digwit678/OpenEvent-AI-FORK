from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")


def _state(tmp_path: Path) -> WorkflowState:
    message = IncomingMessage(
        msg_id="msg-vague",
        from_name="Client",
        from_email="client@example.com",
        subject="Saturday availability",
        body="Looking at Saturdays in February for ~30 guests.",
        ts="2025-12-01T09:00:00Z",
    )
    return WorkflowState(message=message, db_path=tmp_path / "events.json", db={"events": []})


def test_step3_includes_available_dates_for_vague_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = _state(tmp_path)
    state.event_id = "EVT-VAGUE"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    state.user_info = {
        "range_query_detected": True,
        "vague_month": "February",
        "vague_weekday": "Saturday",
    }
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "14.02.2026",
        "date_confirmed": True,
        "thread_state": "Awaiting Client",
        "requirements": {"number_of_participants": 30},
        "requirements_hash": "hash",
        "room_eval_hash": None,
    }

    iso_candidates = ["2026-02-01", "2026-02-08", "2026-02-15", "2026-02-22", "2026-02-29"]

    monkeypatch.setattr(room_module, "_dates_in_month_weekday_wrapper", lambda *_args, **_kwargs: list(iso_candidates))
    monkeypatch.setattr(room_module, "_closest_alternatives_wrapper", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        room_module,
        "evaluate_room_statuses",
        lambda _db, _date: [{"Room A": "Available"}, {"Room B": "Option"}],
    )

    available_room_a = {"01.02.2026", "08.02.2026", "15.02.2026"}
    available_room_b = {"01.02.2026", "08.02.2026", "15.02.2026"}

    def fake_room_status_on_date(_db, date_ddmmyyyy, room_name):
        if room_name == "Room A" and date_ddmmyyyy in available_room_a:
            return "Available"
        if room_name == "Room B" and date_ddmmyyyy in available_room_b:
            return "Option"
        return "Unavailable"

    monkeypatch.setattr(room_module, "room_status_on_date", fake_room_status_on_date)

    result = room_module.process(state)
    assert result.action == "room_avail_result"

    draft = state.draft_messages[-1]
    body_md = draft.get("body_markdown") or draft["body"]
    assert "### Room A" in body_md
    assert "Available dates" in body_md
    assert "Room A" in body_md and "Room B" in body_md

    for action in draft["actions"]:
        assert action["type"] == "select_room"
        assert action["available_dates"], "Expected available_dates for each select_room action."

    first_row = draft["table_blocks"][0]["rows"][0]
    assert first_row["available_dates"], "Table rows should expose available_dates."
