from __future__ import annotations

import pytest

from backend.agents import validate_tool_call, ToolExecutionError


def test_step_two_denies_room_tools() -> None:
    state = {"current_step": 2}
    with pytest.raises(ToolExecutionError):
        validate_tool_call("tool_room_status_on_date", state)


def test_step_three_allows_room_tools() -> None:
    state = {"current_step": 3}
    validate_tool_call("tool_room_status_on_date", state)


def test_client_tools_bypass_allowlist() -> None:
    state = {"current_step": 4}
    # Should not raise even though not in allowlist.
    validate_tool_call("client_confirm_offer", state)
