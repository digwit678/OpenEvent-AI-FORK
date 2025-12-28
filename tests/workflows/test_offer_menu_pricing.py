import importlib
from pathlib import Path

from backend.domain import IntentLabel
from backend.workflows.common.types import IncomingMessage, WorkflowState


offer_module = importlib.import_module("backend.workflows.steps.step4_offer.trigger.step4_handler")


def _base_event_entry() -> dict:
    return {
        "event_id": "evt-menu",
        "current_step": 4,
        "thread_state": "Awaiting Client",
        "chosen_date": "14.02.2026",
        "locked_room_id": "Room A",
        "requirements": {"number_of_participants": 30},
        # Explicitly set base_rate to 0 to test product pricing only (no room rental)
        "pricing_inputs": {"base_rate": 0},
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
        },
        "products": [
            {"name": "Background Music Package", "quantity": 1, "unit_price": 180.0, "unit": "per_event"},
            {"name": "Wireless Microphone", "quantity": 1, "unit_price": 25.0, "unit": "per_unit"},
            # Regression: menu items should be per event, not multiplied by participants.
            {"name": "Seasonal Garden Trio", "quantity": 30, "unit_price": 92.0},
        ],
    }


def test_menu_priced_per_event_not_participants(tmp_path: Path) -> None:
    """Test that menu items are priced per-event, not per-participant.

    This test validates the menu normalization logic:
    - Menu items with quantity matching participant count should normalize to quantity=1
    - Total should reflect per-event pricing (not quantity * unit_price if menu)
    """
    event_entry = _base_event_entry()

    pricing_inputs = offer_module._rebuild_pricing_inputs(event_entry, {})
    line_items = pricing_inputs.get("line_items") or []

    items_by_name = {item["description"]: item for item in line_items}
    menu_line = items_by_name["Seasonal Garden Trio"]
    # Menu normalization should set quantity=1 for per_event items
    assert menu_line["quantity"] == 1
    assert menu_line["amount"] == 92.0

    # Note: _determine_offer_total includes room rate (500 for Room A).
    # Expected: room_rate(500) + music(180) + mic(25) + menu(92) = 797
    total = offer_module._determine_offer_total(event_entry, pricing_inputs.get("total_amount"))
    assert total == 797.0  # 500 (room) + 180 + 25 + 92

    # Create a minimal state for _compose_offer_summary
    msg = IncomingMessage.from_dict({
        "msg_id": "msg-test",
        "from_name": "Client",
        "from_email": "client@example.com",
        "subject": "Test",
        "body": "",
        "ts": "2025-11-25T00:00:00Z",
    })
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db={"events": []})
    state.event_entry = event_entry

    summary_lines = offer_module._compose_offer_summary(event_entry, total, state)
    assert any("1× Seasonal Garden Trio" in line for line in summary_lines)
    assert all("30× Seasonal Garden Trio" not in line for line in summary_lines)
    assert any("(per event)" in line for line in summary_lines if "Seasonal Garden Trio" in line)


def test_plain_acceptance_goes_to_hil(tmp_path: Path) -> None:
    event_entry = _base_event_entry()
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
            "msg_id": "msg-accept",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Offer reply",
            "body": "ok thats fine",
            "ts": "2025-11-25T00:00:00Z",
        }
    )
    state = WorkflowState(message=msg, db_path=tmp_path / "events.json", db=db)
    state.intent = IntentLabel.EVENT_REQUEST
    state.current_step = 4
    state.event_entry = event_entry
    state.user_info = {}

    result = offer_module.process(state)

    assert result.action == "offer_accept_pending_hil"
    assert state.thread_state == "Waiting on HIL"
    assert state.event_entry.get("current_step") == 5
    pending = state.event_entry.get("negotiation_pending_decision")
    assert pending and pending.get("type") == "accept"
