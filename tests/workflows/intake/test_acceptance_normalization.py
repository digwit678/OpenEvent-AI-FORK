from pathlib import Path

import importlib
import pytest

from backend.domain import IntentLabel
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState


def test_curly_apostrophe_acceptance_routes_to_hil(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    intake_module = importlib.import_module("backend.workflows.steps.step1_intake.trigger.step1_handler")

    # Force classifier to downgrade the intent so the heuristic must detect acceptance.
    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(intake_module, "extract_user_information", lambda _payload: {})

    # Requirements must include all fields that build_requirements produces to avoid hash mismatch.
    # event_duration={} (not None) is important because build_requirements creates {} for empty durations.
    requirements = {
        "number_of_participants": 30,
        "seating_layout": None,
        "event_duration": {},
        "special_requirements": None,
        "preferred_room": None,
    }
    req_hash = requirements_hash(requirements)

    event_entry = {
        "event_id": "EVT-ACCEPT",
        "current_step": 5,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
        "chosen_date": "27.02.2026",
        "locked_room_id": "Room A",
        "offers": [{"offer_id": "EVT-ACCEPT-1"}],
        "current_offer_id": "EVT-ACCEPT-1",
        "requirements": requirements,
        "requirements_hash": req_hash,
        "event_data": {"Email": "laura.meier@bluewin.ch"},
    }
    db = {
        "events": [event_entry],
        "clients": {
            "laura.meier@bluewin.ch": {
                "profile": {"name": None, "org": None, "phone": None},
                "history": [],
                "event_ids": [event_entry["event_id"]],
            }
        },
        "tasks": [],
    }

    message = IncomingMessage(
        msg_id="msg-accept",
        from_name="Laura",
        from_email="laura.meier@bluewin.ch",
        subject="Re: Offer",
        body="that’s fine",  # curly apostrophe
        ts="2025-11-25T00:43:16Z",
    )
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)

    result = intake_module.process(state)

    assert result.action == "intake_complete"
    assert state.intent == IntentLabel.EVENT_REQUEST
    assert state.user_info.get("hil_approve_step") == 5
    assert state.event_entry.get("current_step") == 5
    assert state.event_entry.get("thread_state") == "Waiting on HIL"
