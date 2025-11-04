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
    from backend.debug.trace import BUS, emit

    _reset_bus(THREAD_ID)

    emit(
        THREAD_ID,
        "ENTITY_CAPTURE",
        step="Step1_Intake",
        detail="participants (llm)",
        data={"value": 25},
        subject="participants",
        status="captured",
    )
    emit(
        THREAD_ID,
        "GATE_PASS",
        step="Step2_Date",
        detail="date_confirmed",
        data={"date_confirmed": True},
        subject="date_confirmed",
        status="pass",
    )
    emit(
        THREAD_ID,
        "DB_WRITE",
        step="db.events.update",
        detail="WRITE",
        data={"event_id": "evt-1"},
        subject="db.events.update",
        status="changed",
    )

    client = TestClient(main.app)
    response = client.get(f"/api/debug/threads/{THREAD_ID}")
    assert response.status_code == 200

    payload = response.json()
    assert payload["thread_id"] == THREAD_ID
    assert payload["confirmed"] == {
        "date": False,
        "room_locked": False,
        "requirements_hash_matches": False,
    }

    trace = payload["trace"]
    assert len(trace) >= 3

    first = trace[0]
    assert first["subject"] == "participants"
    assert first["status"] == "captured"
    assert first["summary"].startswith("participants=")
    assert first["lane"] == "entity"

    gate = next(event for event in trace if event["kind"] == "GATE_PASS")
    assert gate["status"] == "pass"
    assert gate["lane"] == "gate"
    assert gate["summary"].startswith("date_confirmed")

    db_event = trace[-1]
    assert db_event["lane"] == "db"
    assert db_event["status"] == "changed"
    assert "WRITE" in db_event["summary"].upper()

    # arrow log export mirrors enriched payload
    text_response = client.get(f"/api/debug/threads/{THREAD_ID}/timeline/text")
    assert text_response.status_code == 200
    body = text_response.text
    assert "participants" in body
    assert "Gate" in body
    assert "DB" in body

    _reset_bus(THREAD_ID)
