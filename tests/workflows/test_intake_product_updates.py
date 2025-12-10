from __future__ import annotations

import importlib

intake_module = importlib.import_module("backend.workflows.groups.intake.trigger.process")


def _message(body: str) -> dict:
    return {"subject": "Update", "body": body}


def test_menu_addition_is_treated_as_product_update() -> None:
    user_info: dict = {}

    detected = intake_module._detect_product_update_request(  # type: ignore[attr-defined]
        _message("pls add Alpine Roots Degustation to the offer"),
        user_info,
        linked_event={"event_data": {"Number of Participants": 30}},
    )

    assert detected is True
    additions = user_info.get("products_add") or []
    menu = next(item for item in additions if item["name"] == "Alpine Roots Degustation")
    assert menu["quantity"] == 1  # dinner menus are per event
    assert menu.get("unit") == "per_event"
    assert menu.get("unit_price") == 105.0


def test_menu_removal_is_detected() -> None:
    user_info: dict = {}

    detected = intake_module._detect_product_update_request(  # type: ignore[attr-defined]
        _message("please remove Alpine Roots Degustation from the offer"),
        user_info,
        linked_event=None,
    )

    assert detected is True
    removals = [name.lower() for name in user_info.get("products_remove") or []]
    assert "alpine roots degustation" in removals


def test_existing_menu_op_already_triggers_update_detection() -> None:
    user_info = {
        "products_add": [
            {"name": "Alpine Roots Degustation", "unit_price": 105.0, "unit": "per_event"},
        ]
    }

    detected = intake_module._detect_product_update_request(  # type: ignore[attr-defined]
        _message(""),
        user_info,
        linked_event=None,
    )

    assert detected is True
    additions = user_info.get("products_add") or []
    assert any(item["name"] == "Alpine Roots Degustation" for item in additions)
