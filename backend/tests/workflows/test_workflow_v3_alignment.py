import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflow_email import load_db, process_msg  # noqa: E402
from backend.domain import TaskType  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Dict[str, Any]]:
    os.environ["AGENT_MODE"] = "stub"
    from backend.workflows.llm import adapter as llm_adapter

    mapping: Dict[str, Dict[str, Any]] = {}
    intent_overrides: Dict[str, str] = {}

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    if hasattr(llm_adapter.adapter, "extract_user_information"):
        monkeypatch.setattr(llm_adapter.adapter, "extract_user_information", fake_extract, raising=False)
    else:
        monkeypatch.setattr(llm_adapter.adapter, "extract_entities", fake_extract, raising=False)

    original_route = llm_adapter.adapter.route_intent

    def fake_route(payload: Dict[str, Any]) -> Any:
        msg_id = payload.get("msg_id")
        if msg_id in intent_overrides:
            return intent_overrides[msg_id], 0.99
        return original_route(payload)

    monkeypatch.setattr(llm_adapter.adapter, "route_intent", fake_route, raising=False)

    mapping["__intent_overrides__"] = intent_overrides
    return mapping


def _message(body: str, *, msg_id: str) -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Alex Client",
        "from_email": "client@example.com",
        "subject": "Event request",
        "ts": "2025-01-01T09:00:00Z",
        "body": body,
    }


def _run(
    db_path: Path,
    mapping: Dict[str, Dict[str, Any]],
    msg_id: str,
    body: str,
    *,
    info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if info is not None:
        mapping[msg_id] = info
    return process_msg(_message(body, msg_id=msg_id), db_path=db_path)


def _event(db_path: Path) -> Dict[str, Any]:
    db = load_db(db_path)
    assert db["events"], "Expected an event to be created"
    return db["events"][0]


def test_intake_guard_manual_review(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "intake.json"
    _stub_agent["__intent_overrides__"]["m1"] = "other"
    msg = _message("Hello team, just saying hi.", msg_id="m1")

    result = process_msg(msg, db_path=db_path)
    db = load_db(db_path)

    assert result["action"] == "manual_review_enqueued"
    assert not db["events"]
    assert db["tasks"]
    assert db["tasks"][0]["type"] == TaskType.MANUAL_REVIEW.value
    assert all(draft["requires_approval"] for draft in result["draft_messages"])


def test_step2_five_date_loop_and_confirmation(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "step2.json"
    mapping = _stub_agent

    result1 = _run(
        db_path,
        mapping,
        "m1",
        "We'd like to host a workshop and need available dates.",
    )
    assert result1["action"] == "date_options_proposed"
    assert result1["thread_state"] == "Awaiting Client Response"

    result2 = _run(
        db_path,
        mapping,
        "m2",
        "Let's confirm 15.03.2025 for the workshop.",
        info={"date": "2025-03-15"},
    )
    assert result2["action"] == "date_time_clarification"
    event = _event(db_path)
    assert event["chosen_date"] == "15.03.2025"
    assert event.get("pending_time_request")


def test_step2_confirm_parses_time_range_dash(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "step2-time.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "m1",
        "We'd like to see some dates for April 2026.",
    )

    result = _run(
        db_path,
        mapping,
        "m2",
        "Confirm 09.04.2026, 18-22.",
        info={"date": "2026-04-09"},
    )
    assert result["action"] == "room_avail_result"

    event = _event(db_path)
    assert event["event_data"]["Start Time"] == "18:00"
    assert event["event_data"]["End Time"] == "22:00"
    requested = event.get("requested_window") or {}
    assert requested.get("start_time") == "18:00"
    assert requested.get("end_time") == "22:00"
    assert requested.get("times_inherited") is False


def test_step2_confirm_without_time_requests_clarification(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]
) -> None:
    db_path = tmp_path / "step2-missing-time.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "m1",
        "Looking at possible dates in April.",
    )

    result = _run(
        db_path,
        mapping,
        "m2",
        "Confirm 09.04.2026.",
        info={"date": "2026-04-09"},
    )
    assert result["action"] == "date_time_clarification"

    event = _event(db_path)
    pending = event.get("pending_time_request") or {}
    assert pending.get("iso_date") == "2026-04-09"
    assert event["date_confirmed"] is False
    assert event["thread_state"] == "Awaiting Client Response"


def test_happy_path_step3_to_4_hil_gate(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "step3_hil.json"
    mapping = _stub_agent

    result = _run(
        db_path,
        mapping,
        "m1",
        "We'd like to book Room A on 20.05.2025 for 18 people.",
        info={"date": "2025-05-20", "participants": 18, "room": "Room A"},
    )
    assert result["action"] == "room_avail_result"
    event = _event(db_path)
    assert event["current_step"] == 3
    assert event.get("room_pending_decision")
    assert event["locked_room_id"] is None

    approval = _run(
        db_path,
        mapping,
        "hil",
        "HIL approves Room A.",
        info={"hil_approve_step": 3},
    )
    assert approval["action"] == "offer_draft_prepared"
    event = _event(db_path)
    assert event["current_step"] == 5
    assert event["caller_step"] is None
    assert event["locked_room_id"] == "Room A"
    assert event["room_eval_hash"] == event["requirements_hash"]
    audit_pairs = {(entry["from_step"], entry["to_step"], entry["reason"]) for entry in event["audit"]}
    assert (3, 4, "room_hil_approved") in audit_pairs
