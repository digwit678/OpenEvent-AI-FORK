from __future__ import annotations

import importlib
from pathlib import Path
from typing import Dict, Any

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState


def _initial_event() -> Dict[str, Any]:
    return {
        "event_id": "EVT-FOLLOWUP",
        "client_id": "laura@example.com",
        "current_step": 2,
        "thread_state": "Awaiting Client",
        "date_confirmed": False,
        "range_query_detected": True,
        "vague_month": "february",
        "vague_weekday": "saturday",
        "requirements": {
            "number_of_participants": 30,
            "range_query_detected": True,
            "vague_month": "february",
            "vague_weekday": "saturday",
            "wish_products": ["sound system"],
        },
        "requested_window": {
            "display_date": "07.02.2026",
            "date_iso": "2026-02-07",
            "start_time": "18:00",
            "end_time": "22:00",
            "start": "2026-02-07T17:00:00+01:00",
            "end": "2026-02-07T22:00:00+01:00",
            "times_inherited": False,
            "partial": False,
            "hash": "prev-hash",
        },
        "event_data": {
            "Email": "laura@example.com",
            "Event Date": "Not specified",
            "Start Time": "Not specified",
            "End Time": "Not specified",
            "Number of Participants": "30",
        },
    }


def _build_state(tmp_path: Path) -> WorkflowState:
    existing_event = _initial_event()
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
        msg_id="msg-followup",
        from_name="Laura",
        from_email="laura@example.com",
        subject="Re: Private Dinner Event – Date Options in February",
        body="07.02.2026",
        ts="2025-11-14T01:35:00Z",
    )
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-followup"
    return state


def test_date_confirmation_falls_back_to_workflow_when_room_autorun_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")
    date_module = importlib.import_module("backend.workflows.groups.date_confirmation.trigger.process")

    # Force the short reply to map back into the automated date-follow-up path.
    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(
        intake_module,
        "extract_user_information",
        lambda _payload: {
            "event_date": "07.02.2026",
            "range_query_detected": True,
            "vague_month": "february",
            "vague_weekday": "saturday",
            "wish_products": ["sound system"],
        },
    )

    # Simulate a runtime failure inside Step-3 to ensure we surface the fallback.
    def _boom(_state: WorkflowState) -> None:
        raise RuntimeError("room engine offline")

    room_module = importlib.import_module("backend.workflows.groups.room_availability.trigger.process")
    monkeypatch.setattr(room_module, "process", _boom)

    state = _build_state(tmp_path)

    intake_module.process(state)
    state.user_info.setdefault("start_time", "18:00")
    state.user_info.setdefault("end_time", "22:00")
    state.user_info.setdefault("date", "2026-02-07")

    result = date_module.process(state)

    assert result.action == "date_confirmed"
    assert result.halt is False, "fallback must allow orchestrator to keep progressing to Step-3"
    assert result.payload.get("room_autorun_failed") is True
    assert state.extras.get("room_autorun_failed") is True
    assert state.current_step == 3
    assert state.draft_messages, "fallback acknowledgement should still be drafted"
    assert state.draft_messages[0]["body_markdown"].startswith("Next step")
