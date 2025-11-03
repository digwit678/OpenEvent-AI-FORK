"""Behavioural tests that ensure workflow prompts follow the Workflow v3 copy."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflow_email import load_db, process_msg
from backend.workflows.common.prompts import FOOTER_SEPARATOR


@pytest.fixture(autouse=True)
def _force_stub_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic stub adapter for repeatable expectations."""

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("INTENT_FORCE_EVENT_REQUEST", "1")
    from backend.workflows.llm import adapter as llm_adapter

    llm_adapter.reset_llm_adapter()


@pytest.fixture
def _frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze ``datetime.date.today`` so ordinal date parsing stays deterministic."""

    from backend.workflows.llm import adapter as llm_adapter

    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> dt.date:
            return cls(2025, 1, 10)

    monkeypatch.setattr(llm_adapter.dt, "date", _FixedDate)


def _message(body: str, *, msg_id: str = "m1") -> Dict[str, str]:
    return {
        "msg_id": msg_id,
        "from_name": "Taylor Client",
        "from_email": "taylor@example.com",
        "subject": "Event inquiry",
        "ts": "2025-01-10T09:00:00Z",
        "body": body,
    }


def _draft_by_topic(drafts: List[Dict[str, str]], topic: str) -> Dict[str, str]:
    for draft in drafts:
        if draft.get("topic") == topic:
            return draft
    raise AssertionError(f"Draft with topic '{topic}' not found. Available: {[d.get('topic') for d in drafts]}")


def _extract_body_and_footer(message: str) -> tuple[str, str]:
    assert FOOTER_SEPARATOR in message, "Expected UX footer separator to be present"
    body, footer = message.split(FOOTER_SEPARATOR, 1)
    assert footer.startswith("Step:"), footer
    assert "Next:" in footer and "State:" in footer, footer
    return body.strip(), footer.strip()


def test_regex_date_integration_and_prompt_copy(tmp_path: Path, _frozen_today: None) -> None:
    """End-to-end check that regex extraction feeds the Workflow v3 prompts."""

    db_path = tmp_path / "workflow.json"

    first_result = process_msg(
        _message(
            "Hello, we’d like to plan a workshop and need possible dates in March.",
            msg_id="m1",
        ),
        db_path=db_path,
    )

    assert first_result["action"] == "date_options_proposed"
    date_body, date_footer = _extract_body_and_footer(
        _draft_by_topic(first_result["draft_messages"], "date_candidates")["body"]
    )
    assert "Here are our next available dates" in date_body
    assert "If you have alternatives, please share them" in date_body
    assert "Step:" in date_footer and "Next:" in date_footer

    second_result = process_msg(
        _message(
            "Let’s lock the 15th of March 2025 for around 60 guests in Room B.",
            msg_id="m2",
        ),
        db_path=db_path,
    )

    assert second_result["action"] == "room_avail_result"

    drafts = second_result["draft_messages"]
    confirmation_body, confirmation_footer = _extract_body_and_footer(
        _draft_by_topic(drafts, "date_confirmation")["body"]
    )
    assert "Thank you for confirming 15.03.2025" in confirmation_body
    assert confirmation_footer.startswith("Step: 2")

    try:
        availability_body, availability_footer = _extract_body_and_footer(
            _draft_by_topic(drafts, "room_available")["body"]
        )
        assert "Good news — Room B is available on 15.03.2025" in availability_body
        assert availability_body.endswith("Shall we proceed with this room and date?")
    except AssertionError:
        availability_body, availability_footer = _extract_body_and_footer(
            _draft_by_topic(drafts, "room_option")["body"]
        )
        assert "Room B is currently on option for 15.03.2025" in availability_body
        assert availability_body.endswith("what would you prefer?")

    assert "60 guests" in availability_body
    assert availability_footer.startswith("Step: 3")

    event_entry = load_db(db_path)["events"][0]
    assert event_entry["chosen_date"] == "15.03.2025"
    assert event_entry.get("requirements", {}).get("number_of_participants") == 60
    assert event_entry.get("locked_room_id") is None


def test_infer_date_from_body_handles_ordinals(_frozen_today: None) -> None:
    """Directly exercise the ordinal regex fallback used in stub mode."""

    from backend.workflows.llm import adapter as llm_adapter

    inferred = llm_adapter._infer_date_from_body("Could we meet on the 3rd of April?")
    assert inferred == "2025-04-03"


def test_room_availability_shortcut_capacity_flag(tmp_path: Path, _frozen_today: None) -> None:
    """Ensure capacity hints are suppressed when shortcut_capacity_ok is true."""

    db_path = tmp_path / "shortcut.json"

    initial = process_msg(
        _message("Hi! Can you share availability for Room C in late March?", msg_id="m1"),
        db_path=db_path,
    )
    assert initial["action"] == "date_options_proposed"

    combined = process_msg(
        _message(
            "Let’s confirm 15.03.2025 in Room B — capacity is fine, please use the capacity shortcut.",
            msg_id="m2",
        ),
        db_path=db_path,
    )

    try:
        availability = _draft_by_topic(combined["draft_messages"], "room_available")
    except AssertionError:
        availability = _draft_by_topic(combined["draft_messages"], "room_option")
    body, footer = _extract_body_and_footer(availability["body"])
    assert "It comfortably fits" not in body
    assert footer.startswith("Step: 3")
