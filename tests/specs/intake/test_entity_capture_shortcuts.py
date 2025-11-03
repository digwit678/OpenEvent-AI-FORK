import json
from pathlib import Path

from ...utils.assertions import assert_no_duplicate_prompt

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "intake_loops.json"


def test_capacity_shortcut_not_asked_twice():
    payloads = json.loads(FIXTURE.read_text())
    capacity_prompt = {
        "text": "Step: 1 Intake · Next: Tell us the expected capacity · State: Awaiting Client",
        "field": "capacity",
    }

    # Intake captured the capacity early via shortcut
    intake_state = {"capacity": payloads["shortcut_capacity_ok"]["capacity"]}

    # Step 3 prompts should not request capacity again once stored
    step3_prompts = [
        {
            "text": "Step: 3 Room Availability · Next: Choose a room layout · State: Awaiting Client",
            "field": "seating_layout",
        }
    ]

    assert_no_duplicate_prompt([capacity_prompt] + step3_prompts, prompt_key="capacity")
    assert intake_state["capacity"] == 60


def test_wish_products_capture_does_not_gate():
    payloads = json.loads(FIXTURE.read_text())
    shortcut_text = payloads["shortcut_wish_products"]["text"]

    thread_state = {
        "step": 1,
        "wish_products": ["Projector", "Apéro"],
        "next_step": 2,
    }

    assert "projector" in shortcut_text.lower()
    assert thread_state["next_step"] == 2
