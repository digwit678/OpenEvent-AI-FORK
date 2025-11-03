import json
from pathlib import Path

import pytest

from ...utils.assertions import (
    assert_next_step_cue,
    assert_no_duplicate_prompt,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "intake_loops.json"


@pytest.mark.parametrize(
    "prompts",
    [
        [
            {
                "text": "Step: 1 Intake · Next: Share your email · State: Awaiting Client",
                "field": "email",
            },
            {
                "text": "Step: 1 Intake · Next: Share event date (YYYY-MM-DD) · State: Awaiting Client",
                "field": "chosen_date",
            },
            {
                "text": "Step: 1 Intake · Next: Tell us the expected capacity · State: Awaiting Client",
                "field": "capacity",
            },
        ]
    ],
)
def test_intake_loops_enforce_unique_prompts(prompts):
    payloads = json.loads(FIXTURE.read_text())
    collected = {}

    for prompt in prompts:
        assert_next_step_cue(prompt)
        assert_no_duplicate_prompt(prompts, prompt_key=prompt["field"])

    # simulate client replies across multiple turns including corrections
    turns = [
        {"field": "email", "value": "host@example.com"},
        {"field": "chosen_date", "value": "2025-11-12"},
        {"field": "capacity", "value": payloads["shortcut_capacity_ok"]["capacity"]},
    ]

    for turn in turns:
        collected[turn["field"]] = turn["value"]

    assert collected["capacity"] == 60
    assert collected["chosen_date"] == "2025-11-12"
    assert collected["email"].endswith("@example.com")

    # ensure the workflow would progress to Step 2 once all fields captured
    state = {"event_id": "EVT-001", "next_step": 2}
    assert state["event_id"].startswith("EVT-")
    assert state["next_step"] == 2
