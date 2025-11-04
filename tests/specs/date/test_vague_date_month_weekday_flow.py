from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.workflows.common.datetime_parse import (
    enumerate_month_weekday,
    month_name_to_number,
    weekday_name_to_number,
)
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.groups.date_confirmation.trigger.process import _present_candidate_dates

from ...utils.timezone import freeze_time


def _state(tmp_path: Path) -> WorkflowState:
    msg = IncomingMessage(
        msg_id="msg-vague",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Saturday in February",
        body="We'd like a Saturday evening in February for about 30 guests.",
        ts="2024-12-10T09:00:00Z",
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "vague-dates.json", db={"events": []})
    state.client_id = "laura@example.com"
    return state


def test_vague_month_weekday_enumeration(tmp_path):
    state = _state(tmp_path)
    event_entry = {
        "event_id": "EVT-VAGUE",
        "requirements": {"preferred_room": "Room A"},
        "thread_state": "Awaiting Client",
        "current_step": 2,
        "vague_month": "February",
        "vague_weekday": "Saturday",
        "vague_time_of_day": "evening",
    }
    state.event_entry = event_entry
    state.user_info = {
        "vague_month": "February",
        "vague_weekday": "Saturday",
        "vague_time_of_day": "evening",
    }

    with freeze_time("2024-12-15 09:00:00"):
        _present_candidate_dates(state, event_entry)

    draft = state.draft_messages[-1]
    block = draft["table_blocks"][0]
    rows = block["rows"]
    actions = draft["actions"]

    assert block["type"] == "dates"
    assert "Saturdays in February" in block.get("label", "")
    assert len(rows) == len(actions)
    assert all(action["type"] == "select_date" for action in actions)

    today = date.today()
    month_number = month_name_to_number("February")
    weekday_number = weekday_name_to_number("Saturday")
    expected_iso: list[str] = []
    if month_number is not None and weekday_number is not None:
        for year in (today.year, today.year + 1):
            candidates = [
                candidate
                for candidate in enumerate_month_weekday(year, month_number, weekday_number)
                if candidate >= today
            ]
            if candidates:
                expected_iso = [candidate.isoformat() for candidate in candidates]
                break
    expected_iso = expected_iso[: len(rows)]
    produced_iso = [row["iso_date"] for row in rows]

    assert produced_iso[: len(expected_iso)] == expected_iso
    assert all(row.get("time_of_day") == "Evening" for row in rows)
    assert all("Evening" in action["label"] for action in actions)

    stored_candidates = event_entry.get("candidate_dates") or []
    assert stored_candidates == [action["date"] for action in actions]
