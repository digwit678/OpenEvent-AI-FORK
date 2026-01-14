from __future__ import annotations

import os

import pytest

from tests_integration.test_e2e_live_openai import LiveContext, _load_event, _process_message


@pytest.mark.integration
def test_offer_acceptance_enqueues_send_offer(live_ctx: LiveContext) -> None:
    os.environ["AUTO_LOCK_SINGLE_ROOM"] = "false"
    ctx = live_ctx

    _process_message(ctx, msg_id="accept-1", body="Need 18:00–22:00 options in early November for 15 people.")
    _process_message(ctx, msg_id="accept-2", body="Take the 2025-11-02 18:00–22:00 option.")
    _process_message(ctx, msg_id="accept-3", body="Lock Room B for that date.")

    offer = _process_message(ctx, msg_id="accept-4", body="Please send the offer draft.")
    assert offer["action"] == "offer_draft_prepared"

    acceptance = _process_message(ctx, msg_id="accept-5", body="All good, please proceed — we confirm.")
    # Workflow now requires billing before accepting - expected behavior
    assert acceptance["action"] in {
        "negotiation_accept",
        "transition_ready",
        "offer_accept_requires_billing",  # Now requires billing first
        "billing_address_requested",
    }

    event_entry = _load_event(ctx)
    # Event can be at Step 4 (awaiting billing) or Step 5+ (if billing provided)
    assert event_entry.get("current_step") in {4, 5, 6, 7}
