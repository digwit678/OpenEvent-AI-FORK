from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from domain import IntentLabel
from workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, db: dict, message: IncomingMessage) -> WorkflowState:
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-followup"
    return state


def test_followup_date_confirmation_stays_in_automation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    intake_module = importlib.import_module("workflows.steps.step1_intake.trigger.step1_handler")

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

    # For events at step > 1, the manual review check is skipped and intent is not boosted.
    # The event is passed to downstream step handlers (Step 2) for processing.
    # The key assertion is that we link to the existing event and extract the date.
    assert state.event_entry is not None
    assert state.event_entry["event_id"] == "EVT-FOLLOWUP"
    assert state.user_info.get("event_date") == "07.02.2026"
    # Automation continues without HIL drafts at intake level
    assert not state.draft_messages, "Follow-up confirmations should stay in automation without HIL drafts"


def test_followup_confirmation_with_awaiting_client_response_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("workflows.steps.step1_intake.trigger.step1_handler")

    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(
        intake_module,
        "extract_user_information",
        lambda _payload: {"event_date": "20.11.2026", "start_time": "18:00", "end_time": "22:00"},
    )

    existing_event = {
        "event_id": "EVT-FOLLOWUP",
        "client_id": "patrick.keller@veritas-advisors.ch",
        "current_step": 2,
        "thread_state": "Awaiting Client Response",
        "date_confirmed": False,
        "candidate_dates": ["2026-11-20"],
        "requirements": {"number_of_participants": 80},
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
        msg_id="msg-followup-response",
        from_name="Patrick Keller",
        from_email="patrick.keller@veritas-advisors.ch",
        subject="Re: Client Appreciation Event – Date options",
        body="2026-11-20 18:00–22:00",
        ts="2025-11-17T20:11:00Z",
    )

    state = _state(tmp_path, db, message)

    intake_module.process(state)

    # For events at step > 1, the manual review check is skipped and intent is not boosted.
    # The event is passed to downstream step handlers (Step 2) for processing.
    # The key assertion is that we link to the existing event and extract the date/times.
    assert state.event_entry is not None
    assert state.event_entry["event_id"] == "EVT-FOLLOWUP"
    assert state.user_info.get("event_date") == "20.11.2026"
    assert state.user_info.get("start_time") == "18:00"
    assert state.user_info.get("end_time") == "22:00"
    # Automation continues without HIL drafts at intake level
    assert not state.draft_messages
