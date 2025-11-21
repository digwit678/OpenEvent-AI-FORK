import json
from pathlib import Path

import pytest

from backend.domain import IntentLabel
from backend.workflows.llm import adapter as llm_adapter

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
                "footer": "Step: 1 Intake · Next: Share your email · State: Awaiting Client",
                "body_markdown": "Could we have your email address to keep you posted?",
                "field": "email",
            },
            {
                "footer": "Step: 1 Intake · Next: Share event date (YYYY-MM-DD) · State: Awaiting Client",
                "body_markdown": "What's the confirmed date for your event?",
                "field": "chosen_date",
            },
            {
                "footer": "Step: 1 Intake · Next: Tell us the expected capacity · State: Awaiting Client",
                "body_markdown": "How many guests should we plan for?",
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


def test_structured_analysis_fallback(monkeypatch):
    class BrokenAdapter(llm_adapter.StubAgentAdapter):
        def analyze_message(self, msg):  # type: ignore[override]
            raise ValueError("malformed json")

    monkeypatch.setattr(llm_adapter, "get_agent_adapter", lambda: BrokenAdapter())
    llm_adapter.reset_llm_adapter()

    intent, confidence = llm_adapter.classify_intent({"subject": "Hello", "body": "Event for 20 people"})
    assert intent in {IntentLabel.EVENT_REQUEST, IntentLabel.NON_EVENT}
    assert 0.0 <= confidence <= 1.0

    user_info = llm_adapter.extract_user_information({"subject": "Catering", "body": "We need projector"})
    assert isinstance(user_info, dict)