from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from backend.agents.openevent_agent import OpenEventAgent


@pytest.mark.live_smoke
def test_live_smoke_agent_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Exercise the live OpenEvent provider via the Agents SDK when a real OpenAI key is available.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not configured for live smoke tests.")

    monkeypatch.setenv("AGENT_MODE", "openai")
    monkeypatch.setenv("OPENAI_TEST_MODE", "1")

    agent = OpenEventAgent()
    session = agent.create_session("live-smoke-thread")

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    message = {
        "msg_id": "live-smoke-msg",
        "from_name": "Smoke Test",
        "from_email": "smoke-test@example.com",
        "subject": "Live Smoke Sanity Check",
        "ts": timestamp,
        "body": "Hello OpenEvent, please acknowledge this smoke test run.",
    }

    response = agent.run(session, message)

    assert isinstance(response, dict), "Agent response should be a dictionary envelope."
    assert response.get("assistant_text"), "Agent response must include assistant text."
    assert response.get("payload"), "Agent response must include a payload."
