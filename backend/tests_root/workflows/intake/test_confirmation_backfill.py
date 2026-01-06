from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, db: dict, message: IncomingMessage) -> WorkflowState:
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-confirmation"
    return state


def test_confirmation_backfill_infers_date_from_short_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("backend.workflows.steps.step1_intake.trigger.step1_handler")

    # Classifier recognizes this as a date confirmation already.
    monkeypatch.setattr(
        intake_module,
        "classify_intent",
        lambda _payload: (IntentLabel.EVENT_REQUEST, 0.98),
    )
    # Extraction fails to parse the ISO string.
    monkeypatch.setattr(
        intake_module,
        "extract_user_information",
        lambda _payload: {"start_time": "18:00", "end_time": "22:00"},
    )

    requirements = {"number_of_participants": 80}
    existing_event = {
        "event_id": "EVT-DATE",
        "client_id": "patrick.keller@veritas-advisors.ch",
        "current_step": 2,
        "thread_state": "Awaiting Client",
        "date_confirmed": False,
        "requirements": requirements,
        "requirements_hash": "hash",
        "event_data": {"Email": "patrick.keller@veritas-advisors.ch"},
    }
    db = {
        "events": [existing_event],
        "clients": {
            "patrick.keller@veritas-advisors.ch": {
                "profile": {"name": None, "org": None, "phone": None},
                "history": [],
                "event_ids": [existing_event["event_id"]],
            }
        },
        "tasks": [],
    }

    message = IncomingMessage(
        msg_id="msg-confirmation",
        from_name="Patrick",
        from_email="patrick.keller@veritas-advisors.ch",
        subject="Re: Date options",
        body="2026-11-20 18:00–22:00",
        ts="2025-11-18T15:17:00Z",
    )

    state = _state(tmp_path, db, message)
    intake_module.process(state)

    assert state.user_info.get("date") == "2026-11-20"
    assert state.user_info.get("event_date") == "20.11.2026"
    assert state.user_info.get("start_time") == "18:00"
    assert state.user_info.get("end_time") == "22:00"
