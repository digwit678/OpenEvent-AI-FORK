from __future__ import annotations

from backend.adapters.client_gui_adapter import adapt_message


def test_adapter_prefers_body_markdown(capsys):
    payload = {
        "body_markdown": "### Room C — Available\n- **Alternative dates (closest):** 01.02., 08.02., 15.02.",
        "prompt": "fallback",
    }

    adapted = adapt_message(payload)
    captured = capsys.readouterr()

    assert "body_chosen=body_markdown" in captured.out
    assert "Room C — Available" in adapted.get("render_body", "")
    assert "Alternative dates (closest)" in adapted["render_body"]
