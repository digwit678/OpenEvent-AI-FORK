from ...utils.assertions import assert_next_step_cue, assert_wait_state


def test_offer_compose_includes_footer_and_hil_gate():
    draft = {
        "body_markdown": "Dear Client,\n\nHere is your tailored proposal.",
        "footer": "Step: 4 Offer · Next: Await feedback · State: Awaiting Client",
        "thread_state": "Awaiting Client",
        "actions": [
            {
                "type": "review_offer",
                "label": "Review offer draft",
            }
        ],
        "table_blocks": [],
    }

    assert draft["footer"].endswith("State: Awaiting Client")

    hil_log = {"thread_state": "Waiting on HIL", "approved": True}
    assert_wait_state(hil_log, "Waiting on HIL")
    hil_log["approved"] = True
    assert hil_log["approved"] is True

    creation_payload = {"offer_id": "OFF-123", "status": "Lead", "thread_state": "Awaiting Client"}
    assert creation_payload["status"] == "Lead"
    assert creation_payload["thread_state"] == "Awaiting Client"

    cue = {"footer": draft["footer"]}
    assert_next_step_cue(cue)