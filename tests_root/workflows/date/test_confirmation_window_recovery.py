from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict

from workflows.common.types import IncomingMessage, WorkflowState


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


def _event_entry_with_candidates(candidate_isos: list[str]) -> Dict[str, Any]:
    return {
        "event_id": "EVT-REL",
        "requirements": {},
        "event_data": {},
        "candidate_dates": candidate_isos,
    }


def test_resolve_confirmation_window_recovers_from_inverted_times(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.step2_handler")

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


def test_relative_confirmation_accepts_weekday_only(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.step2_handler")

    state = _build_state(tmp_path)
    state.message.subject = "Re: Updated room options"
    state.message.body = "Thursday works for us."
    state.message.ts = "2027-03-07T09:00:00Z"
    state.user_info.clear()
    state.user_info["start_time"] = "18:00"
    state.user_info["end_time"] = "22:00"

    event_entry = _event_entry_with_candidates(
        ["2027-03-11", "2027-03-12", "2027-03-18", "2027-03-19"]
    )

    window = module._resolve_confirmation_window(state, event_entry)

    assert window is not None
    assert window.iso_date == "2027-03-11"
    assert window.start_time == "18:00"
    assert window.end_time == "22:00"


def test_relative_confirmation_handles_next_week_reference(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.step2_handler")

    state = _build_state(tmp_path)
    state.message.subject = "Re: New availability window"
    state.message.body = "Friday next week works perfectly."
    state.message.ts = "2027-03-08T09:00:00Z"  # Monday
    state.user_info.clear()
    state.user_info["start_time"] = "18:00"
    state.user_info["end_time"] = "22:00"

    event_entry = _event_entry_with_candidates(
        ["2027-03-11", "2027-03-12", "2027-03-18", "2027-03-19"]
    )

    window = module._resolve_confirmation_window(state, event_entry)

    assert window is not None
    assert window.iso_date == "2027-03-19"


def test_relative_confirmation_handles_next_month_reference(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.step2_handler")

    state = _build_state(tmp_path)
    state.message.subject = "Re: Updated schedule"
    state.message.body = "Friday next month would be ideal."
    state.message.ts = "2027-03-05T09:00:00Z"
    state.user_info.clear()
    state.user_info["start_time"] = "18:00"
    state.user_info["end_time"] = "22:00"

    # April 2, 2027 is the first Friday in April, so include it in candidates
    event_entry = _event_entry_with_candidates(
        ["2027-03-12", "2027-03-19", "2027-04-02", "2027-04-09", "2027-04-16"]
    )

    window = module._resolve_confirmation_window(state, event_entry)

    assert window is not None
    # "Friday next month" from March should resolve to April 2 (first Friday in April)
    assert window.iso_date == "2027-04-02"


def test_relative_confirmation_handles_month_and_week_ordinal(tmp_path: Path) -> None:
    module = importlib.import_module("backend.workflows.steps.step2_date_confirmation.trigger.step2_handler")

    state = _build_state(tmp_path)
    state.message.subject = "Re: Autumn dates"
    state.message.body = "Friday in the first October week works."
    state.message.ts = "2027-09-25T09:00:00Z"
    state.user_info.clear()
    state.user_info["start_time"] = "18:00"
    state.user_info["end_time"] = "22:00"

    event_entry = _event_entry_with_candidates(
        ["2027-10-01", "2027-10-08", "2027-10-15"]
    )

    window = module._resolve_confirmation_window(state, event_entry)

    assert window is not None
    assert window.iso_date == "2027-10-01"
