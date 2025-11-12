from __future__ import annotations

from backend.chatkit import build_client_tool_message


def test_confirm_offer_message_builds_default() -> None:
    payload = {"client_tool": "confirm_offer", "args": {}}
    assert build_client_tool_message(payload) == "Please confirm the offer."


def test_change_offer_message_includes_note() -> None:
    payload = {"client_tool": "change_offer", "args": {"note": "adjust the start time"}}
    assert "adjust the start time" in build_client_tool_message(payload)


def test_see_catering_with_room() -> None:
    payload = {"client_tool": "see_catering", "args": {"room_id": "Room A"}}
    message = build_client_tool_message(payload)
    assert "Room A" in message
    assert "catering" in message.lower()