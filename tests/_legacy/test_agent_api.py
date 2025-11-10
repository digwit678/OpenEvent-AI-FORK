from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.agents.guardrails import safe_envelope


def test_safe_envelope_validates_schema() -> None:
    envelope = {
        "assistant_text": "Hello!",
        "requires_hil": True,
        "action": "workflow_response",
        "payload": {"foo": "bar"},
    }
    validated = safe_envelope(envelope)
    assert validated["assistant_text"] == "Hello!"
    assert validated["requires_hil"] is True
    assert validated["action"] == "workflow_response"


def test_agent_reply_endpoint_returns_envelope() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/reply",
        json={
            "thread_id": "test-thread",
            "message": "We'd like to plan a workshop in November for 20 people.",
            "from_email": "client@example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "assistant_text" in payload
    assert "requires_hil" in payload
    assert "action" in payload
    assert "payload" in payload