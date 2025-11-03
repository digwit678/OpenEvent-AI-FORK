import json

import pytest

from backend.agents import execute_tool_call, ToolExecutionError
from backend.agents.openevent_agent import OpenEventAgent


def test_tool_schema_blocks_missing_required_fields():
    state = {"current_step": 3}
    with pytest.raises(ToolExecutionError) as exc:
        execute_tool_call(
            tool_name="tool_room_status_on_date",
            tool_call_id="call-missing",
            arguments={"date": "15.03.2025"},
            state=state,
            db={},
        )
    detail = json.loads(str(exc.value))
    assert detail["reason"] == "schema_validation_failed"
    assert "errors" in detail


def test_tool_call_idempotency_uses_cache():
    agent = OpenEventAgent()
    session = agent.create_session("thread-id")
    session["state"].update({"current_step": 2})

    arguments = {
        "event_id": "EVT-123",
        "preferred_room": "Room A",
        "start_from_iso": "2025-11-01T09:00:00",
        "days_ahead": 5,
        "max_results": 3,
    }
    first = agent.execute_tool(
        session,
        tool_name="tool_suggest_dates",
        tool_call_id="call-123",
        arguments=arguments,
        db={"events": []},
    )
    second = agent.execute_tool(
        session,
        tool_name="tool_suggest_dates",
        tool_call_id="call-123",
        arguments={},
        db={"events": []},
    )
    assert first == second


def test_tool_choice_enforces_allowlist():
    state = {"current_step": 2}
    with pytest.raises(ToolExecutionError):
        execute_tool_call(
            tool_name="tool_build_offer_draft",
            tool_call_id="call-999",
            arguments={"event_entry": {}, "user_info": {}},
            state=state,
        )
