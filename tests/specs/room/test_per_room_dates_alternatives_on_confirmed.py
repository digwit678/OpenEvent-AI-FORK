from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.workflows.common.types import IncomingMessage, WorkflowState

room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")


def _state(tmp_path: Path) -> WorkflowState:
    message = IncomingMessage(
        msg_id="msg-alt",
        from_name="Client",
        from_email="client@example.com",
        subject="Confirm 14 Feb",
        body="Prefer Saturday 14 February, happy to consider nearby Saturdays if needed.",
        ts="2025-12-10T09:00:00Z",
    )
    return WorkflowState(message=message, db_path=tmp_path / "events.json", db={"events": []})


def test_step3_lists_alternative_dates_after_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = _state(tmp_path)
    state.event_id = "EVT-ALT"
    state.current_step = 3
    state.set_thread_state("Awaiting Client")
    state.user_info = {}
    state.event_entry = {
        "event_id": state.event_id,
        "chosen_date": "14.02.2026",
        "date_confirmed": True,
        "thread_state": "Awaiting Client",
        "requirements": {"number_of_participants": 28},
        "requirements_hash": "hash",
        "room_eval_hash": None,
    }

    alt_iso = ["2026-02-21", "2026-02-28", "2026-03-07"]

    monkeypatch.setattr(
        room_module,
        "_closest_alternatives_wrapper",
        lambda *_args, **_kwargs: list(alt_iso),
    )
    monkeypatch.setattr(
        room_module,
        "_dates_in_month_weekday_wrapper",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        room_module,
        "evaluate_room_statuses",
        lambda _db, _date: [{"Room A": "Available"}, {"Room B": "Available"}],
    )

    alt_dd = ["21.02.2026", "28.02.2026", "07.03.2026"]

    def fake_room_status_on_date(_db, date_ddmmyyyy, room_name):
        if room_name == "Room A" and date_ddmmyyyy in alt_dd[:2]:
            return "Available"
        if room_name == "Room B" and date_ddmmyyyy in alt_dd:
            return "Available"
        return "Unavailable"

    monkeypatch.setattr(room_module, "room_status_on_date", fake_room_status_on_date)

    result = room_module.process(state)
    assert result.action == "room_avail_result"

    draft = state.draft_messages[-1]
    body_md = draft.get("body_markdown") or draft["body"]
    assert "### Room A" in body_md
    assert "Alternative dates (closest)" in body_md

    for action in draft["actions"]:
        assert "available_dates" in action
        assert len(action["available_dates"]) <= 3
        assert action["type"] == "select_room"
