from __future__ import annotations

import os

import pytest

from tests_integration.test_e2e_live_openai import LiveContext, _load_event, _process_message, _append_failure


@pytest.mark.integration
def test_offer_not_generated_before_lock(live_ctx: LiveContext) -> None:
    os.environ["ALLOW_AUTO_ROOM_LOCK"] = "false"
    ctx = live_ctx
    _process_message(ctx, msg_id="offer-1", body="Need 18:00–22:00 slots in early November for 15 people.")
    second = _process_message(ctx, msg_id="offer-2", body="Take the 2025-11-02 18:00–22:00 option.")
    assert second["action"] != "offer_draft_prepared", "Offer should not be prepared before a lock"
    ev = _load_event(ctx)
    assert ev.get("locked_room_id") in (None, ""), "Room should not be locked before explicit instruction"
    assert not (ev.get("offers") or []), "Offer generated before a room was locked"
    lock_result = _process_message(ctx, msg_id="offer-3", body="Lock Room A for that date.")
    # Combined room+offer flow may generate offer immediately after lock
    assert lock_result["action"] in {"room_auto_locked", "room_lock_retained", "offer_draft_prepared"}
    locked = _load_event(ctx)
    assert locked.get("locked_room_id") == "Room A"
    offer_attempt = _process_message(ctx, msg_id="offer-4", body="Great, please send over the offer draft.")
    try:
        assert offer_attempt["action"] == "offer_draft_prepared", "Offer should be prepared after lock when requested"
    except AssertionError:
        _append_failure(
            ctx,
            reason="offer_not_prepared_after_lock",
            details={
                "last_action": offer_attempt.get("action"),
                "current_step": (_load_event(ctx).get("current_step")),
                "locked_room_id": (_load_event(ctx).get("locked_room_id")),
                "room_decision": (_load_event(ctx).get("room_decision")),
                "requirements_hash": (_load_event(ctx).get("requirements_hash")),
            },
        )
        raise


@pytest.mark.integration
def test_lock_advances_to_step4(live_ctx: LiveContext) -> None:
    os.environ["ALLOW_AUTO_ROOM_LOCK"] = "false"
    ctx = live_ctx
    _process_message(ctx, msg_id="step4-1", body="18:00–22:00 in early November for ~15 people.")
    _process_message(ctx, msg_id="step4-2", body="Take the 2025-11-02 18:00–22:00 option.")
    _process_message(ctx, msg_id="step4-3", body="Please lock Room A for us.")
    ev = _load_event(ctx)
    assert ev.get("locked_room_id") == "Room A"
    # Combined room+offer flow may advance to Step 5 immediately
    assert ev.get("current_step") in {4, 5}, f"Expected to be at Step 4 or 5 after lock, got {ev.get('current_step')}"


@pytest.mark.integration
def test_offer_request_after_lock_routes_to_offer(live_ctx: LiveContext) -> None:
    os.environ["ALLOW_AUTO_ROOM_LOCK"] = "false"
    ctx = live_ctx
    _process_message(ctx, msg_id="route-1", body="Need 18:00–22:00 slots in early November for 15 people.")
    _process_message(ctx, msg_id="route-2", body="Take the 2025-11-02 18:00–22:00 option.")
    _process_message(ctx, msg_id="route-3", body="Lock Room A for that date.")
    after_lock = _load_event(ctx)
    # Combined room+offer flow may advance to Step 5 immediately
    assert after_lock.get("current_step") in {4, 5}
    attempt = _process_message(ctx, msg_id="route-4", body="Please send the offer draft.")
    if attempt.get("action") != "offer_draft_prepared":
        _append_failure(
            ctx,
            reason="offer_request_routed_to_availability",
            details={
                "action": attempt.get("action"),
                "current_step": (_load_event(ctx).get("current_step")),
            },
        )
    assert attempt.get("action") == "offer_draft_prepared"
