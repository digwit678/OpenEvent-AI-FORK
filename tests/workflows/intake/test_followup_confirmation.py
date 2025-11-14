from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, db: dict, message: IncomingMessage) -> WorkflowState:
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-followup"
    return state


def test_followup_date_confirmation_stays_in_automation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")

    # Force the primary intent classifier to misclassify the short reply.
    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(intake_module, "extract_user_information", lambda _payload: {"event_date": "07.02.2026"})

    existing_event = {
        "event_id": "EVT-FOLLOWUP",
        "client_id": "laura@example.com",
        "current_step": 2,
        "thread_state": "Awaiting Client",
        "date_confirmed": False,
        "requirements": {"number_of_participants": 30},
        "event_data": {"Email": "laura@example.com"},
    }
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

    state = _state(tmp_path, db, message)

    intake_module.process(state)

    assert state.intent == IntentLabel.EVENT_REQUEST
    assert state.confidence >= 0.95
    assert state.event_entry is not None
    assert state.event_entry["event_id"] == "EVT-FOLLOWUP"
    assert not state.draft_messages, "Follow-up confirmations should stay in automation without HIL drafts"
