from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState


def _state(tmp_path: Path, db: dict, message: IncomingMessage) -> WorkflowState:
    state = WorkflowState(message=message, db_path=tmp_path / "events.json", db=db)
    state.thread_id = "thread-product-update"
    return state


def test_product_update_followup_skips_manual_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")

    # Force classifier to downgrade confidence so heuristics kick in.
    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.NON_EVENT, 0.2))
    monkeypatch.setattr(intake_module, "extract_user_information", lambda _payload: {})

    manual_review_called = {"value": False}

    def _fake_enqueue(*_args, **_kwargs):
        manual_review_called["value"] = True
        return "TASK-MANUAL"

    monkeypatch.setattr(intake_module, "enqueue_manual_review_task", _fake_enqueue)

    requirements = {"number_of_participants": 80}
    req_hash = requirements_hash(requirements)
    existing_event = {
        "event_id": "EVT-OFFER",
        "client_id": "patrick.keller@veritas-advisors.ch",
        "current_step": 5,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
        "chosen_date": "20.11.2026",
        "locked_room_id": "Room E",
        "room_eval_hash": req_hash,
        "requirements": requirements,
        "requirements_hash": req_hash,
        "products": [
            {"name": "Background Music Package", "quantity": 1, "unit_price": 180.0},
        ],
        "offers": [
            {
                "offer_id": "EVT-OFFER-1",
                "version": 1,
                "status": "Draft",
                "total_amount": 180.0,
            }
        ],
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
        msg_id="msg-product-update",
        from_name="Patrick",
        from_email="patrick.keller@veritas-advisors.ch",
        subject="Re: Offer update",
        body="OK pls add Wireless Microphone",
        ts="2025-11-18T14:55:00Z",
    )

    state = _state(tmp_path, db, message)
    result = intake_module.process(state)

    assert manual_review_called["value"] is False, "Manual review must not be triggered for product edits"
    assert result.action != "manual_review_enqueued"
    assert state.intent == IntentLabel.EVENT_REQUEST
    products_add = state.user_info.get("products_add") or []
    names = {item["name"] for item in products_add}
    assert "Wireless Microphone" in names, "Heuristic parser should capture requested product"


def test_product_update_preserves_requirements_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")

    monkeypatch.setattr(intake_module, "classify_intent", lambda _payload: (IntentLabel.EVENT_REQUEST, 0.96))

    def _fake_extract(_payload):
        return {
            "participants": 80,
            "products_add": [
                {
                    "name": "Wireless Microphone",
                    "quantity": 1,
                    "unit_price": 25.0,
                    "unit": "per_unit",
                    "product_id": "equipment-wireless-mics",
                    "category": "Equipment",
                }
            ],
        }

    monkeypatch.setattr(intake_module, "extract_user_information", _fake_extract)

    requirements = {
        "number_of_participants": 80,
        "seating_layout": "Standing reception",
        "event_duration": {"start": "18:00", "end": "22:00"},
        "special_requirements": "sound system",
        "preferred_room": "Room E",
    }
    req_hash = requirements_hash(requirements)
    event_entry = {
        "event_id": "EVT-PRODUCT-HASH",
        "client_id": "patrick.keller@veritas-advisors.ch",
        "current_step": 5,
        "thread_state": "Awaiting Client",
        "date_confirmed": True,
        "chosen_date": "20.11.2026",
        "locked_room_id": "Room E",
        "room_eval_hash": req_hash,
        "requirements": requirements,
        "requirements_hash": req_hash,
        "products": [
            {"name": "Background Music Package", "quantity": 1, "unit_price": 180.0},
        ],
        "event_data": {"Email": "patrick.keller@veritas-advisors.ch"},
    }
    db = {
        "events": [event_entry],
        "clients": {
            "patrick.keller@veritas-advisors.ch": {
                "profile": {"name": None, "org": None, "phone": None},
                "history": [],
                "event_ids": [event_entry["event_id"]],
            }
        },
        "tasks": [],
    }

    message = IncomingMessage(
        msg_id="msg-product-update-hash",
        from_name="Patrick",
        from_email="patrick.keller@veritas-advisors.ch",
        subject="Re: Offer update",
        body="Please add Wireless Microphone",
        ts="2025-11-18T14:56:00Z",
    )

    state = _state(tmp_path, db, message)
    intake_module.process(state)

    updated_event = state.event_entry
    assert updated_event["requirements_hash"] == req_hash
    assert updated_event.get("requirements") == requirements
