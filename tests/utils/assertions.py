def assert_no_duplicate_prompt(messages, prompt_key):
    def _text(msg):
        if "text" in msg:
            return msg.get("text", "")
        body = msg.get("body_markdown") or ""
        footer = msg.get("footer") or ""
        return f"{body} {footer}".strip()

    count = sum(1 for m in messages if prompt_key in _text(m))
    assert count <= 1


def assert_next_step_cue(msg):
    text = msg.get("text") or msg.get("footer") or ""
    assert any(k in text for k in ["Next:", "Choose", "Please confirm"])


def assert_wait_state(msg, expected):
    state = msg.get("wait_state") or msg.get("thread_state")
    assert state == expected  # "Awaiting Client" | "Waiting on HIL"