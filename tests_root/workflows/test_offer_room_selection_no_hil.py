from __future__ import annotations

from domain import IntentLabel
from workflows.common.types import IncomingMessage, WorkflowState
import importlib

offer_module = importlib.import_module("workflows.steps.step4_offer.trigger.step4_handler")


def _event_entry() -> dict:
    return {
        "event_id": "evt-room",
        "current_step": 4,
        "thread_state": "Awaiting Client",
        "chosen_date": "14.02.2026",
        "locked_room_id": "Room E",
        "requirements": {"number_of_participants": 30},
        "billing_details": {
            "name_or_company": "Test Client",
            "street": "Mainstrasse 1",
            "postal_code": "8000",
            "city": "Zurich",
            "country": "Switzerland",
        },
        "event_data": {
            "Email": "client@example.com",
            "Billing Address": "Test Client, Mainstrasse 1, 8000 Zurich, Switzerland",
            "Name": "Test Client",
            "Number of Participants": "30",
        },
        "products": [
            {"name": "Background Music Package", "quantity": 1, "unit_price": 180.0, "unit": "per_event"},
        ],
    }


def test_room_selection_phrase_does_not_trigger_hil(tmp_path) -> None:
    event_entry = _event_entry()
    db = {
        "events": [event_entry],
        "clients": {
            "client@example.com": {
                "profile": {"name": None, "org": None, "phone": None},
                "history": [],
                "event_ids": [event_entry["event_id"]],
            }
        },
        "tasks": [],
    }

    msg = IncomingMessage.from_dict(
        {
            "msg_id": "msg-room-select",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Client follow-up",
            "body": "Proceed with Room E (Background Music Package)",
            "ts": "2025-11-25T00:00:00Z",
        }
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db=db)
    state.intent = IntentLabel.EVENT_REQUEST
    state.current_step = 4
    state.event_entry = event_entry
    state.user_info = {"room": "Room E", "_room_choice_detected": True}

    result = offer_module.process(state)

    assert result.action != "offer_accept_pending_hil"
    assert state.thread_state != "Waiting on HIL"
    assert not state.event_entry.get("pending_hil_requests")
    assert not state.event_entry.get("negotiation_pending_decision")
