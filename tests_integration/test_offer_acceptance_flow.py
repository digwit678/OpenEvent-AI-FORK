from __future__ import annotations

import os

import pytest

from backend.domain import TaskType
from backend.workflow_email import load_db
from backend.tests_integration.test_e2e_live_openai import LiveContext, _load_event, _process_message


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
    assert acceptance["action"] in {"negotiation_accept", "transition_ready"}
    draft_text = acceptance.get("draft_messages", [])[-1]["body"]
    assert "NEXT STEP:" in draft_text
    assert "We’ll prepare the final offer for approval and sending." in draft_text

    telemetry = acceptance.get("telemetry") or {}
    assert telemetry.get("final_action") == "accepted"

    db_snapshot = load_db(ctx.db_path)
    tasks = db_snapshot.get("tasks", [])
    assert any(task.get("type") == TaskType.ROUTE_POST_OFFER.value for task in tasks)

    event_entry = _load_event(ctx)
    assert event_entry.get("current_step") in {6, 7}
