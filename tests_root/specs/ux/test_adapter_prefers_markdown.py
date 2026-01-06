from __future__ import annotations

import logging

from adapters.client_gui_adapter import adapt_message


def test_adapter_prefers_body_markdown(caplog):
    payload = {
        "body_markdown": "### Room C — Available\n- **Alternative dates (closest):** 01.02., 08.02., 15.02.",
        "prompt": "fallback",
    }

    with caplog.at_level(logging.DEBUG):
        adapted = adapt_message(payload)

    assert "body_chosen=body_markdown" in caplog.text
    assert "Room C — Available" in adapted.get("render_body", "")
    assert "Alternative dates (closest)" in adapted["render_body"]
