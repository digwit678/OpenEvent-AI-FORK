"""
Legacy reference for the real-agent smoke test that previously lived in
``tests/e2e/test_live_smoke.py``. The module name intentionally avoids the
``test_`` prefix so that pytest will not auto-collect or execute it. Keep it
around for future inspiration or manual experiments that need the old logic.
"""

from __future__ import annotations

import os
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict

from backend.agents.openevent_agent import OpenEventAgent


def run_live_smoke_reference() -> Dict[str, Any]:
    """
    Execute the legacy live smoke scenario against the OpenEvent agent.

    Returns the agent response envelope to make it easy to inspect manually.
    Raises ``RuntimeError`` when the required OpenAI configuration is missing.
    """

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured for live smoke tests.")

    previous_agent_mode = os.getenv("AGENT_MODE")
    previous_openai_test_mode = os.getenv("OPENAI_TEST_MODE")
    os.environ["AGENT_MODE"] = "openai"
    os.environ["OPENAI_TEST_MODE"] = "1"

    try:
        agent = OpenEventAgent()
        session = agent.create_session("legacy-live-smoke-thread")

        timestamp = datetime.now(tz=timezone.utc).isoformat()
        message = {
            "msg_id": "legacy-live-smoke-msg",
            "from_name": "Smoke Test",
            "from_email": "smoke-test@example.com",
            "subject": "Legacy Live Smoke Sanity Check",
            "ts": timestamp,
            "body": "Hello OpenEvent, please acknowledge this smoke test run.",
        }

        response = agent.run(session, message)

        if not isinstance(response, dict):
            raise TypeError("Agent response should be a dictionary envelope.")
        if not response.get("assistant_text"):
            raise AssertionError("Agent response must include assistant text.")
        if not response.get("payload"):
            raise AssertionError("Agent response must include a payload.")

        return response
    finally:
        if previous_agent_mode is None:
            with suppress(KeyError):
                del os.environ["AGENT_MODE"]
        else:
            os.environ["AGENT_MODE"] = previous_agent_mode

        if previous_openai_test_mode is None:
            with suppress(KeyError):
                del os.environ["OPENAI_TEST_MODE"]
        else:
            os.environ["OPENAI_TEST_MODE"] = previous_openai_test_mode


if __name__ == "__main__":
    envelope = run_live_smoke_reference()
    print("Agent response:", envelope)
