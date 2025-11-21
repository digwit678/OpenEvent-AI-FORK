from ...utils.assertions import assert_wait_state

CLIENT_SENDS = [
    {"step": 1, "footer": "Step: 1 Intake · Next: Share details · State: Awaiting Client"},
    {"step": 2, "footer": "Step: 2 Date Confirmation · Next: Confirm date · State: Awaiting Client"},
    {"step": 4, "footer": "Step: 4 Offer · Next: Await feedback · State: Awaiting Client"},
]


def test_all_client_sends_require_hil():
    for message in CLIENT_SENDS:
        hil_state = {"thread_state": "Waiting on HIL", "step": message["step"]}
        assert_wait_state(hil_state, "Waiting on HIL")

    mini_loop = {"thread_state": "Awaiting Client", "step": 4, "loop": "tight_products"}
    assert_wait_state(mini_loop, "Awaiting Client")
    assert mini_loop["loop"] == "tight_products"