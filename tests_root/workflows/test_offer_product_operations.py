from __future__ import annotations

from backend.workflows.steps.step4_offer.trigger.step4_handler import (
    _apply_product_operations,
    _compose_offer_summary,
)


def _base_event(products=None):
    return {
        "products": list(products or []),
        "requirements": {"number_of_participants": 80},
    }


def test_apply_product_operations_adds_catalog_item_without_pricing():
    event_entry = _base_event(
        products=[
            {"name": "Classic Apéro", "quantity": 80, "unit_price": 18.0},
        ]
    )

    changed = _apply_product_operations(event_entry, {"products_add": [{"name": "Wireless Microphone"}]})

    assert changed is True
    assert any(item["name"] == "Wireless Microphone" for item in event_entry["products"])
    mic_entry = next(item for item in event_entry["products"] if item["name"] == "Wireless Microphone")
    assert mic_entry["unit_price"] == 25.0
    assert mic_entry["quantity"] == 1


def test_apply_product_operations_updates_existing_product_quantity():
    """Test that adding more of an existing product increments the quantity."""
    event_entry = _base_event(
        products=[
            {"name": "Wireless Microphone", "quantity": 1, "unit_price": 25.0},
        ]
    )

    changed = _apply_product_operations(
        event_entry,
        {"products_add": [{"name": "Wireless Microphone", "quantity": 2}]},
    )

    assert changed is True
    mic_entry = next(item for item in event_entry["products"] if item["name"] == "Wireless Microphone")
    # upsert_product increments quantity (1 existing + 2 added = 3)
    assert mic_entry["quantity"] == 3


def test_apply_product_operations_removes_item_from_dict_payload():
    event_entry = _base_event(
        products=[
            {"name": "Wireless Microphone", "quantity": 1, "unit_price": 25.0},
            {"name": "Classic Apéro", "quantity": 80, "unit_price": 18.0},
        ]
    )

    changed = _apply_product_operations(
        event_entry,
        {"products_remove": [{"name": "Wireless Microphone"}]},
    )

    assert changed is True
    assert all(item["name"] != "Wireless Microphone" for item in event_entry["products"])


def test_apply_product_operations_clears_autofill_summary_matched():
    event_entry = _base_event(
        products=[
            {"name": "Classic Apéro", "quantity": 80, "unit_price": 18.0},
            {"name": "Cocktail Bar Setup", "quantity": 1, "unit_price": 320.0},
        ]
    )
    event_entry["products_state"] = {
        "autofill_summary": {
            "matched": [
                {"name": "Classic Apéro", "quantity": 80, "unit_price": 18.0, "match_pct": 92},
            ],
            "alternatives": [
                {"name": "Wireless Microphone", "match_pct": 50},
            ],
        }
    }

    changed = _apply_product_operations(
        event_entry,
        {"products_add": [{"name": "Wireless Microphone"}]},
    )

    assert changed is True
    summary = event_entry["products_state"].get("autofill_summary")
    assert summary is not None
    assert summary.get("matched") == []
    # Alternatives should remain available for the draft copy.
    assert summary.get("alternatives")


def test_compose_offer_summary_recomputes_total_from_products(tmp_path):
    from pathlib import Path
    from backend.workflows.common.types import IncomingMessage, WorkflowState

    event_entry = {
        "chosen_date": "20.11.2026",
        "locked_room_id": "Room E",
        "products": [
            {"name": "Background Music Package", "quantity": 1, "unit_price": 180.0},
            {"name": "Classic Apéro", "quantity": 80, "unit_price": 18.0},
            {"name": "Cocktail Bar Setup", "quantity": 1, "unit_price": 320.0},
        ],
        "products_state": {"autofill_summary": {}},
    }

    # Create minimal state required by _compose_offer_summary
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

    lines = _compose_offer_summary(event_entry, total_amount=1965.0, state=state)

    # Total includes room rate (1,650) + products (180 + 1,440 + 320) = 3,590
    assert any("**Total: CHF 3,590.00**" in line for line in lines), (
        f"Summary must reflect product totals. Lines: {lines}"
    )
