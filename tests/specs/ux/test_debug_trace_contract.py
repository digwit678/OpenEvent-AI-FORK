from __future__ import annotations

import importlib
from typing import Any

from fastapi.testclient import TestClient


THREAD_ID = "contract-thread"


def _reload_main(monkeypatch) -> Any:
    monkeypatch.setenv("DEBUG_TRACE", "1")
    module = importlib.import_module("backend.main")
    return importlib.reload(module)


def _reset_bus(thread_id: str) -> None:
    from backend.debug.trace import BUS

    try:
        BUS._buf.pop(thread_id, None)  # type: ignore[attr-defined]
    except AttributeError:
        pass


def test_trace_event_contract(monkeypatch):
    main = _reload_main(monkeypatch)
    from backend.debug.trace import BUS
    from backend.debug.hooks import trace_entity, trace_gate, trace_db_write, trace_state

    _reset_bus(THREAD_ID)

    trace_entity(THREAD_ID, "Step1_Intake", "participants", "llm", True, {"value": 25})
    trace_gate(THREAD_ID, "Step2_Date", "P1 date_confirmed", True, {"date_confirmed": True})
    trace_db_write(THREAD_ID, "Step1_Intake", "db.events.update", {"event_id": "evt-1"}, duration_ms=12)
    trace_state(THREAD_ID, "Step1_Intake", {"thread_state": "Awaiting Client"})

    client = TestClient(main.app)
    response = client.get(f"/api/debug/threads/{THREAD_ID}")
    assert response.status_code == 200

    payload = response.json()
    assert payload["thread_id"] == THREAD_ID
    assert payload["confirmed"]["date"]["confirmed"] is False
    assert payload["confirmed"]["room_status"] is None
    assert payload["confirmed"]["hash_status"] is None
    assert payload["summary"]["hash_help"]

    trace = payload["trace"]
    assert len(trace) == 3

    first = trace[0]
    assert first["entity"] == "Agent"
    assert first["actor"] == "Agent"
    assert first["subject"] == "participants"
    assert first["status"] == "captured"
    assert "participants" in first["summary"].lower()
    assert first["granularity"] == "logic"
    assert first["captured_additions"] == ["participants=25"]
    assert first["confirmed_now"] == []
    assert isinstance(first["detail"], dict)
    assert first["detail"].get("fn") == "llm"

    gate = next(event for event in trace if event["kind"] == "GATE_PASS")
    assert gate["status"] == "pass"
    assert gate["entity"] == "Condition"
    assert gate["gate"]["met"] in (0, 1)
    assert gate["gate"]["required"] >= 1

    db_event = trace[-1]
    assert db_event["entity"] == "DB Action"
    assert db_event["status"] == "changed"
    assert db_event["io"]["op"] == "db.events.update"
    assert db_event["io"]["direction"] == "WRITE"
    assert db_event["detail"].get("fn") == "db.events.update"

    # arrow log export mirrors enriched payload
    text_response = client.get(f"/api/debug/threads/{THREAD_ID}/timeline/text")
    assert text_response.status_code == 200
    body = text_response.text
    assert "participants" in body
    assert "Gate PASS" in body
    assert "db.events.update" in body

    _reset_bus(THREAD_ID)
