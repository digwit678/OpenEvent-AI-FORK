def assert_no_duplicate_prompt(messages, prompt_key):
    count = sum(1 for m in messages if prompt_key in m.get("text", ""))
    assert count <= 1


def assert_next_step_cue(msg):
    text = msg.get("text", "")
    assert any(k in text for k in ["Next:", "Choose", "Please confirm"])


def assert_wait_state(msg, expected):
    assert msg.get("wait_state") == expected  # "Awaiting Client" | "Waiting on HIL"
