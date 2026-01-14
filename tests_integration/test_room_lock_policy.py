from __future__ import annotations

import os

import pytest

from tests_integration.test_e2e_live_openai import LiveContext, _load_event, _process_message


@pytest.mark.integration
def test_no_auto_lock_when_flag_false(live_ctx: LiveContext) -> None:
    os.environ["ALLOW_AUTO_ROOM_LOCK"] = "false"
    ctx = live_ctx
    _process_message(ctx, msg_id="policy-1", body="We want 18:00–22:00 in November for about 15 people.")
    _process_message(ctx, msg_id="policy-2", body="Take 2025-11-02 18:00–22:00 for the workshop.")
    ev = _load_event(ctx)
    locked_room = ev.get("locked_room_id")
    assert locked_room in (None, ""), f"Locked too early: {locked_room}"
    # room_decision.status may not be populated - just verify locked_room_id is not set


@pytest.mark.integration
@pytest.mark.parametrize("explicit_command", ["Please lock Room B for us.", "take Room B"])
def test_explicit_lock_is_required(live_ctx: LiveContext, explicit_command: str) -> None:
    os.environ["ALLOW_AUTO_ROOM_LOCK"] = "false"
    ctx = live_ctx
    _process_message(
        ctx,
        msg_id="explicit-1",
        body="We want 18:00–22:00 in November for about 15 people. Preferred room: Room B.",
    )
    _process_message(ctx, msg_id="explicit-2", body="Confirm 2025-11-02 18:00–22:00 for the workshop.")
    ev = _load_event(ctx)
    assert ev.get("locked_room_id") in (None, ""), "Preferred room must not lock by itself"
    _process_message(ctx, msg_id="explicit-3", body=explicit_command)
    locked_event = _load_event(ctx)
    assert locked_event.get("locked_room_id") == "Room B", f"Explicit lock failed: {locked_event.get('locked_room_id')}"
    # room_decision.status may not be populated - locked_room_id is the authoritative indicator
