from __future__ import annotations

from backend.agents.openevent_agent import OpenEventAgent


def test_email_composer_prefers_body_markdown(capsys):
    workflow_result = {
        "draft_messages": [
            {
                "body_markdown": "### Room C — Available\n- **Alternative dates (closest):** 01.02., 08.02., 15.02.",
                "footer": "Step: 3 Room Availability · Next: Choose a room · State: Awaiting Client",
            }
        ]
    }

    reply = OpenEventAgent._compose_reply(workflow_result)
    captured = capsys.readouterr().out

    assert "Room C — Available" in reply
    assert "Alternative dates (closest)" in reply
    assert "01.02." in reply
    assert "body_chosen=" in captured
