from __future__ import annotations

from backend.llm.intent_classifier import classify_intent
from backend.main import _compose_turn_drafts
from backend.workflows.qna.router import route_general_qna


def _build_msg(text: str) -> dict:
    return {
        "msg_id": "test",
        "body": text,
        "subject": "Client message",
        "from_email": "client@example.com",
        "from_name": "Client",
    }


def test_mixed_step_and_qna_turn_precedence() -> None:
    text = "Second week of December (around 10/11) for ~22 ppl U-shape. Do rooms have HDMI?"
    classification = classify_intent(text, current_step=2)
    assert classification["primary"] == "date_confirmation"
    assert "rooms_by_feature" in classification["secondary"]

    qna_payload = route_general_qna(
        _build_msg(text),
        event_entry_before=None,
        event_entry_after=None,
        db=None,
        classification=classification,
    )
    assert qna_payload["pre_step"], "Expected HDMI Q&A to appear before the step block"
    assert not qna_payload["post_step"], "No post-step Q&A expected in this scenario"

    info_block = qna_payload["pre_step"][0]["body"]
    assert info_block.startswith("INFO:")
    assert "Proceed with Room Availability" in info_block


def test_compose_turn_drafts_strips_extra_next_step() -> None:
    step_drafts = [
        {
            "body": (
                "ROOM OPTIONS:\n"
                "- Room B — Available on 20.03.2026 18:00–22:00\n"
                "\n"
                "NEXT STEP:\n"
                "- Tell me which room you'd like me to reserve."
            )
        }
    ]
    qna_payload = {
        "pre_step": [
            {
                "body": (
                    "INFO:\n"
                    "- Since you asked about HDMI, here are the rooms that already cover that.\n"
                    "\n"
                    "NEXT STEP:\n"
                    "- Proceed with Room Availability?"
                )
            }
        ],
        "post_step": [
            {
                "body": (
                    "INFO:\n"
                    "- Underground parking at Europaallee is two minutes from the venue with direct lift access.\n"
                    "\n"
                    "NEXT STEP:\n"
                    "- Proceed with Room Availability?"
                )
            }
        ],
    }
    drafts, _ = _compose_turn_drafts(step_drafts, qna_payload, None)
    assert len(drafts) == 3
    step_body = drafts[0]["body"]
    pre_body = drafts[1]["body"]
    post_body = drafts[2]["body"]

    assert "ROOM OPTIONS:" in step_body
    assert step_body.count("NEXT STEP:") == 1

    assert pre_body.startswith("INFO:")
    assert "NEXT STEP:" not in pre_body

    assert post_body.startswith("INFO:")
    assert "NEXT STEP:" not in post_body