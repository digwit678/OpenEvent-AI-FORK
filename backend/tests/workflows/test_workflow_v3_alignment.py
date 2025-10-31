import os
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, Optional, List

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflow_email import load_db, process_msg, save_db  # noqa: E402
from backend.workflows.common.requirements import requirements_hash  # noqa: E402
from backend.workflows.common.types import IncomingMessage, WorkflowState  # noqa: E402
from backend.workflows.planner import maybe_run_smart_shortcuts  # noqa: E402
import backend.workflows.groups.room_availability.trigger.process as room_trigger  # noqa: E402

date_trigger_module = importlib.import_module(
    "backend.workflows.groups.date_confirmation.trigger.process"
)
from backend.domain import TaskType  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Dict[str, Any]]:
    os.environ["AGENT_MODE"] = "stub"
    monkeypatch.setenv("ALLOW_AUTO_ROOM_LOCK", "false")
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


def test_delta_availability_when_comparing_dates(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]
) -> None:
    db_path = tmp_path / "delta-summary.json"
    mapping = _stub_agent

    initial = _run(
        db_path,
        mapping,
        "initial",
        "Could you host us on 10.04.2026 for 20 guests in Room A?",
        info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "participants": 20,
            "room": "Room A",
        },
    )
    if initial["action"] == "date_confirmed":
        next_response = _run(
            db_path,
            mapping,
            "initial-follow",
            "Great, thanks.",
        )
        assert next_response["action"] == "room_avail_result"
        initial = next_response
    assert initial["action"] == "room_avail_result"

    delta = _run(
        db_path,
        mapping,
        "delta",
        "What about 19.04 instead?",
        info={"date": "2026-04-19"},
    )
    assert delta["action"] == "room_delta_summary"
    assert delta["delta_availability_used"] is True
    draft_body = delta["draft_messages"][-1]["body"].lower()
    assert "here's what changed" in draft_body
    assert draft_body.count("would you like to") == 1
    telemetry = delta["telemetry"]
    assert telemetry["delta_availability_used"] is True
    assert telemetry["answered_question_first"] is True
    assert telemetry["gatekeeper_passed"]["step3"] is False


def _set_products(
    event: Dict[str, Any],
    *,
    available: Optional[List[Dict[str, Any]]] = None,
    manager: Optional[List[Dict[str, Any]]] = None,
) -> None:
    state = event.setdefault(
        "products_state",
        {
            "available_items": [],
            "manager_added_items": [],
            "line_items": [],
            "pending_hil_requests": [],
            "budgets": {},
        },
    )
    if available is not None:
        state["available_items"] = available
    if manager is not None:
        state["manager_added_items"] = manager


def _invoke_shortcuts(
    db_path: Path,
    event_id: str,
    *,
    user_info: Dict[str, Any],
    msg_id: str = "shortcut",
    body: str = "",
) -> Dict[str, Any]:
    db = load_db(db_path)
    event = next(evt for evt in db.get("events", []) if evt.get("event_id") == event_id)
    message = IncomingMessage.from_dict(
        {
            "msg_id": msg_id,
            "from_name": "Alex Client",
            "from_email": "client@example.com",
            "subject": "Event request",
            "ts": "2025-01-01T09:00:00Z",
            "body": body,
        }
    )
    state = WorkflowState(message=message, db_path=db_path, db=db)
    state.event_entry = event
    state.event_id = event_id
    state.client_id = "client@example.com"
    state.client = {"email": "client@example.com"}
    state.user_info = user_info
    state.current_step = event.get("current_step")
    result = maybe_run_smart_shortcuts(state)
    assert result is not None, "Smart shortcuts did not run"
    payload = result.payload if hasattr(result, "payload") else result
    save_db(state.db, db_path)
    return payload


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
    start_time = requested.get("start_time") or event.get("event_data", {}).get("Start Time")
    end_time = requested.get("end_time") or event.get("event_data", {}).get("End Time")
    assert start_time == "18:00"
    assert end_time == "22:00"
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


def test_present_candidate_dates_sets_future_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "present-candidates.json"
    message = IncomingMessage.from_dict(
        {
            "msg_id": "past-date",
            "from_name": "Client",
            "from_email": "client@example.com",
            "subject": "Event request",
            "ts": "2025-01-01T09:00:00Z",
            "body": "We're looking at March 20, 2024 around 14:00–20:00 for 45 guests. Do you have availability?",
        }
    )
    state = WorkflowState(message=message, db_path=db_path, db={"events": [], "tasks": []})
    state.client_id = "client@example.com"
    event_entry: Dict[str, Any] = {
        "event_id": "evt-unit",
        "requirements": {"number_of_participants": 45},
    }
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = 2
    state.user_info = {
        "date": "2024-03-20",
        "start_time": "14:00",
        "end_time": "20:00",
        "participants": 45,
        "layout": "Standing reception",
    }

    result = date_trigger_module._present_candidate_dates(
        state,
        event_entry,
        reason="That date is already in the past."
    )
    assert result.action == "date_options_proposed"
    pending_future = event_entry.get("pending_future_confirmation")
    assert isinstance(pending_future, dict)
    assert pending_future.get("display_date")
    body = state.draft_messages[-1]["body"].lower()
    assert "would" in body and "work for you instead" in body


def test_gatekeeping_dates_block_until_complete_window(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMART_SHORTCUTS", raising=False)
    db_path = tmp_path / "gatekeeper-dates.json"
    mapping = _stub_agent

    first = _run(db_path, mapping, "lead", "We are planning a workshop and need April dates.")
    assert first["action"] == "date_options_proposed"

    partial = _run(
        db_path,
        mapping,
        "partial",
        "10.04.2026 works for us.",
        info={"date": "2026-04-10"},
    )
    assert partial["action"] == "date_time_clarification"
    gatekeeper_state = partial.get("gatekeeper_passed")
    assert isinstance(gatekeeper_state, dict)
    assert gatekeeper_state.get("step2") is False
    event = _event(db_path)
    assert event["current_step"] == 2

    complete = _run(
        db_path,
        mapping,
        "time",
        "Let's take 18:00-22:00 then.",
        info={"date": "2026-04-10", "start_time": "18:00", "end_time": "22:00"},
    )
    assert complete["action"] in {"room_avail_result", "smart_shortcut_processed"}
    event = _event(db_path)
    requested = event.get("requested_window") or {}
    start_time = requested.get("start_time") or event.get("event_data", {}).get("Start Time")
    end_time = requested.get("end_time") or event.get("event_data", {}).get("End Time")
    assert start_time == "18:00"
    assert end_time == "22:00"


def test_menus_blocked_before_room_check(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("SMART_SHORTCUTS_MAX_COMBINED", "2")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    db_path = tmp_path / "menus-pre-room.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event_id = event["event_id"]
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "01.05.2026"
    event["requested_window"] = {
        "date_iso": "2026-05-01",
        "start_time": "10:00",
        "end_time": "14:00",
    }
    event["current_step"] = 4
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"date": "2026-04-10", "start_time": "18:00", "end_time": "22:00"},
        msg_id="menus-pre",
        body="Confirm 10.04.2026 18-22 and please send your menus.",
    )

    message = payload["message"]
    assert "Combined confirmation:" in message
    assert "Add-ons (optional)" in message
    assert "Catering menus:" in message
    assert "date_confirmation" in payload["executed_intents"]
    assert "room_selection" not in payload["executed_intents"]
    assert payload["menus_included"] == "preview"
    assert payload["menus_phase"] == "explicit_request"
    assert payload["room_checked"] is True


def test_delta_availability_when_user_changes_date(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMART_SHORTCUTS", raising=False)

    db_path = tmp_path / "delta-availability.json"
    mapping = _stub_agent

    def fake_room_status(db: Dict[str, Any], date_ddmmyyyy: Optional[str], room_name: str) -> str:
        if not date_ddmmyyyy:
            return "Unavailable"
        if room_name == "Room B" and date_ddmmyyyy == "19.04.2026":
            return "Unavailable"
        if room_name in {"Room A", "Room B"} and date_ddmmyyyy == "20.04.2026":
            return "Available"
        if room_name == "Room A" and date_ddmmyyyy == "19.04.2026":
            return "Available"
        return "Unavailable"

    monkeypatch.setattr(room_trigger, "room_status_on_date", fake_room_status, raising=False)
    assert room_trigger.room_status_on_date is fake_room_status

    _run(db_path, mapping, "lead", "Initial request for April slots.")
    _run(
        db_path,
        mapping,
        "confirm",
        "Confirm 20.04.2026 18-22 works.",
        info={"date": "2026-04-20", "start_time": "18:00", "end_time": "22:00"},
    )

    delta = _run(
        db_path,
        mapping,
        "delta",
        "What about 19.04 instead?",
        info={"date": "2026-04-19"},
    )

    assert delta["action"] == "room_delta_summary"
    assert delta["delta_availability_used"] is True
    assert delta["answered_question_first"] is True
    comparison = delta.get("comparison") or {}
    baseline_status = comparison.get("reference_status") or {}
    query_status = comparison.get("query_status") or {}
    diff_rooms = [room for room in query_status if query_status.get(room) != baseline_status.get(room)]
    message = delta["draft_messages"][-1]["body"].lower()
    assert "here's what changed" in message
    assert "would you like to keep" in message
    if not diff_rooms:
        assert "no availability changes" in message


def test_explicit_menus_only_after_room_lock(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("SMART_SHORTCUTS_MAX_COMBINED", "2")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    db_path = tmp_path / "menus-post-room.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    event["locked_room_id"] = "Room B"
    event_id = event["event_id"]
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"participants": 24, "billing_address": "Example AG"},
        msg_id="menus-post",
        body="Please send your catering menu.",
    )

    message = payload["message"]
    lines = [line for line in message.splitlines() if line.strip()]
    assert "Combined confirmation:" in lines
    assert "Next question:" in lines
    assert "Add-ons (optional)" in lines
    assert lines.index("Add-ons (optional)") > lines.index("Next question:")
    assert any(line.startswith("Catering menus:") for line in lines)
    assert payload["menus_included"] == "preview"
    assert payload["menus_phase"] == "explicit_request"
    assert payload["room_checked"] is True


def test_shortcut_date_and_room_combined_confirmation(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    db_path = tmp_path / "smart-combined.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "lead",
        "Hello, initial request.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 2
    event["chosen_date"] = None
    event["requirements"] = {"number_of_participants": 20}
    event["requirements_hash"] = requirements_hash(event["requirements"])
    event["room_pending_decision"] = {
        "selected_room": "Room B",
        "selected_status": "Available",
        "requirements_hash": event["requirements_hash"],
    }
    save_db(db, db_path)

    result = _run(
        db_path,
        mapping,
        "combo",
        "Confirm 10.04.2026 18-22 and take Room B.",
        info={"date": "2026-04-10", "start_time": "18:00", "end_time": "22:00", "room": "Room B"},
    )

    assert result["action"] == "smart_shortcut_processed"
    assert result["combined_confirmation"] is True
    message = result["message"]
    assert "Date confirmed" in message
    assert "Room locked" in message
    assert result["needs_input_next"] == "offer_prepare"
    assert result["executed_intents"] == ["date_confirmation", "room_selection"]

    db = load_db(db_path)
    event = db["events"][0]
    assert event["locked_room_id"] == "Room B"


def test_shortcut_cap_defers_product_add_with_followup(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("SMART_SHORTCUTS_MAX_COMBINED", "2")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    db_path = tmp_path / "smart-cap.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "lead",
        "Initial request.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 2
    event["chosen_date"] = None
    event["requirements"] = {"number_of_participants": 18}
    event["requirements_hash"] = requirements_hash(event["requirements"])
    event["room_pending_decision"] = {
        "selected_room": "Room B",
        "selected_status": "Available",
        "requirements_hash": event["requirements_hash"],
    }
    _set_products(
        event,
        available=[{"name": "Projector", "unit_price": 120.0}],
    )
    save_db(db, db_path)

    result = _run(
        db_path,
        mapping,
        "cap",
        "Confirm 09.04.2026 18-22, lock Room B, add projector.",
        info={
            "date": "2026-04-09",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
            "products_add": [{"name": "Projector"}],
        },
    )

    assert result["action"] == "smart_shortcut_processed"
    assert result["executed_intents"] == ["date_confirmation", "room_selection"]
    assert any(
        item["type"] == "product_add" and item.get("reason_deferred") == "combined_limit_reached"
        for item in result["pending_intents"]
    )
    assert result["needs_input_next"] == "product_followup"
    assert "I queued Projector" in result["message"]
    assert "Add-ons (optional)" not in result["message"]
    assert result["menus_included"] == "false"
    assert result["room_checked"] is True


def test_confirm_date_inherit_time_single_question(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    db_path = tmp_path / "smart-inherit.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "lead",
        "Hello, initial request.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 2
    event_data = event.setdefault("event_data", {})
    event_data["Start Time"] = "18:00"
    event_data["End Time"] = "22:00"
    requirements = event.setdefault("requirements", {})
    requirements["event_duration"] = {"start": "18:00", "end": "22:00"}
    event["requirements_hash"] = requirements_hash(event["requirements"])
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    save_db(db, db_path)

    result = _run(
        db_path,
        mapping,
        "confirm",
        "Confirm 10.04.2026.",
        info={"date": "2026-04-10"},
    )

    assert result["action"] == "smart_shortcut_processed"
    message = result["message"]
    assert "Date confirmed" in message
    assert "Next question" not in message


def test_products_all_exist_added_in_confirmation(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("LEGACY_SHORTCUTS_ALLOWED", "1")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    db_path = tmp_path / "products-all.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event.setdefault("requirements", {})["number_of_participants"] = 18
    _set_products(
        event,
        available=[
            {"name": "Projector", "unit_price": 150.0},
            {"name": "Handheld Mic", "unit_price": 25.0},
        ],
    )
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    event["current_step"] = 4
    event_id = event["event_id"]
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "products_add": [
                {"name": "Projector"},
                {"name": "Handheld Mic", "quantity": 2},
            ],
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
        },
        msg_id="products",
        body="Confirm 10.04.2026 18-22 and add projector plus 2 handheld mic.",
    )

    assert payload["combined_confirmation"] is True
    message = payload["message"]
    assert "Date confirmed" in message
    assert "Products added:" not in message
    assert payload["needs_input_next"] == "availability"
    deferred = payload["pending_intents"]
    assert any(item["type"] == "product_add" and item.get("reason_deferred") == "products_require_room" for item in deferred)
    event = _event(db_path)
    products = event.get("products") or []
    assert not products


def test_products_partial_exist_offer_hil_and_capture_budget(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("LEGACY_SHORTCUTS_ALLOWED", "1")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    db_path = tmp_path / "products-partial.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event.setdefault("requirements", {})["number_of_participants"] = 10
    _set_products(
        event,
        available=[{"name": "Projector"}],
    )
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    event["current_step"] = 4
    event_id = event["event_id"]
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "products_add": [
                {"name": "Projector"},
                {"name": "HDMI Cable"},
            ],
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "billing_address": "Example Strasse 1",
        },
        msg_id="partial",
        body="Confirm 10.04.2026 18-22 and add projector plus HDMI cable. Budget CHF 60 total.",
    )

    assert payload["combined_confirmation"] is True
    message = payload["message"]
    assert "Date confirmed" in message
    assert "price pending" not in message.lower()
    assert payload["needs_input_next"] == "availability"
    deferred = payload["pending_intents"]
    assert any(item["type"] == "offer_hil" and item.get("reason_deferred") == "missing_products" for item in deferred)
    assert any(item["type"] == "product_add" and item.get("reason_deferred") == "products_require_room" for item in deferred)
    assert any(item["type"] == "billing" and item.get("reason_deferred") == "billing_after_offer" for item in deferred)
    assert payload["artifact_match"] == "partial"
    assert payload["product_price_missing"] is True
    assert payload["product_prices_included"] is False
    event = _event(db_path)
    assert not (event.get("products") or [])


def test_products_none_exist_offer_hil_no_menus(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("LEGACY_SHORTCUTS_ALLOWED", "1")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    db_path = tmp_path / "products-none.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    event["current_step"] = 4
    event_id = event["event_id"]
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "products_add": [{"name": "HDMI Cable"}],
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
        },
        msg_id="missing",
        body="Confirm 10.04.2026 18-22 and add an HDMI cable?",
    )

    assert payload["combined_confirmation"] is True
    message = payload["message"]
    assert payload["needs_input_next"] == "offer_hil"
    assert "manager" in message.lower()
    assert "Add-ons (optional)" not in message
    assert payload["menus_included"] == "false"
    assert payload["menus_phase"] == "none"
    assert payload["artifact_match"] == "none"


def test_event_scoped_upsell_brief_line_when_manager_added(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    db_path = tmp_path / "upsell.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    event["locked_room_id"] = "Room B"
    _set_products(
        event,
        manager=[{"class": "catering", "name": "Coffee & Tea"}, {"class": "av", "name": "Projector"}],
    )
    event_id = event["event_id"]
    save_db(db, db_path)

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"participants": 22, "billing_address": "Example AG"},
        msg_id="upsell",
        body="Headcount is now 22.",
    )

    message = payload["message"]
    assert "Would you like to see catering options" in message
    assert "Would you like to see AV add-ons" in message
    assert "Bar Tables" not in message
    preask_shown = payload.get("preask_shown") or []
    assert "catering" in preask_shown and "av" in preask_shown
    assert payload["menus_included"] == "brief_upsell"
    assert payload["menus_phase"] == "post_room"
    assert payload["room_checked"] is True


def test_missing_product_budget_marks_price_pending(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("BUDGET_PARSE_STRICT", "true")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    db_path = tmp_path / "products-budget.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event_id = event["event_id"]

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "products_add": [{"name": "HDMI Cable"}],
            "date": "2026-05-01",
            "start_time": "10:00",
            "end_time": "14:00",
            "budget_total": {"amount": 30, "currency": "CHF", "scope": "total", "text": "CHF 30 total"},
        },
        msg_id="budget-missing",
        body="Add an HDMI cable; budget CHF 30 total.",
    )

    message = payload["message"]
    assert payload["needs_input_next"] == "offer_hil"
    assert "price pending (via manager)" in message.lower()
    assert "with budget CHF 30 total" in message
    assert payload["budget_provided"] is True
    assert payload["product_prices_included"] is False
    assert payload["product_price_missing"] is True
    assert payload["menus_included"] == "false"
    assert "Add-ons (optional)" not in message


def test_idempotent_readdition_merges_line_items(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    monkeypatch.setenv("LEGACY_SHORTCUTS_ALLOWED", "1")
    db_path = tmp_path / "products-idempotent.json"
    mapping = _stub_agent

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    _set_products(event, available=[{"name": "Projector"}])
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    save_db(db, db_path)

    _run(db_path, mapping, "lead", "Initial request.")

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    _set_products(event, available=[{"name": "Projector"}])
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    event_id = event["event_id"]
    save_db(db, db_path)

    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"products_add": [{"name": "Projector"}]},
        msg_id="first",
        body="Add projector.",
    )

    payload = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"products_add": [{"name": "Projector", "quantity": 2}]},
        msg_id="second",
        body="Add projector again with quantity 2.",
    )

    assert payload["combined_confirmation"] is True
    event = _event(db_path)
    products = event.get("products") or []
    assert len(products) == 1
    assert products[0]["quantity"] == 2


def test_overstuffed_message_defers_lower_priority_items(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("ATOMIC_TURNS", "0")
    monkeypatch.setenv("LEGACY_SHORTCUTS_ALLOWED", "1")
    db_path = tmp_path / "smart-overstuffed.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "lead",
        "Initial lead.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    event.setdefault("requirements", {})["number_of_participants"] = 22
    _set_products(
        event,
        available=[{"name": "Projector", "unit_price": 150.0}],
    )
    event["locked_room_id"] = "Room B"
    event["date_confirmed"] = True
    event["chosen_date"] = "10.04.2026"
    event["requested_window"] = {
        "date_iso": "2026-04-10",
        "start_time": "18:00",
        "end_time": "22:00",
    }
    save_db(db, db_path)

    result = _run(
        db_path,
        mapping,
        "over",
        "Confirm 10.04.2026 18-22; we are 22 people; please add a projector and HDMI cable.",
        info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "participants": 22,
            "products_add": [{"name": "Projector"}, {"name": "HDMI Cable"}],
        },
    )

    assert result["action"] == "smart_shortcut_processed"
    assert result["combined_confirmation"] is True
    assert result["needs_input_next"] == "availability"
    pending = result["pending_intents"] or []
    assert any(item["type"] == "offer_hil" for item in pending)
    assert any(item["type"] == "product_add" and item.get("reason_deferred") == "products_require_room" for item in pending)
    message = result["message"]
    assert "Headcount updated" in message
    assert "projector" not in message.lower()


def test_flag_off_preserves_legacy_flow(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMART_SHORTCUTS", raising=False)
    db_path = tmp_path / "legacy.json"
    mapping = _stub_agent

    result1 = _run(
        db_path,
        mapping,
        "lead",
        "Initial message.",
    )
    assert result1["action"] == "date_options_proposed"

    result2 = _run(
        db_path,
        mapping,
        "confirm",
        "Confirm 10.04.2026 18-22.",
        info={"date": "2026-04-10", "start_time": "18:00", "end_time": "22:00"},
    )
    assert result2["action"] != "smart_shortcut_processed"


def test_telemetry_records_partitioning_and_next_question(
    tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    db_path = tmp_path / "smart-telemetry.json"
    mapping = _stub_agent

    _run(
        db_path,
        mapping,
        "lead",
        "Initial.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 2
    save_db(db, db_path)

    result = _run(
        db_path,
        mapping,
        "tele",
        "Confirm 10.04.2026 and send invoice to Example AG.",
        info={"date": "2026-04-10", "billing_address": "Example AG"},
    )

    assert result["action"] == "smart_shortcut_processed"
    assert result["needs_input_next"] == "time"
    db = load_db(db_path)
    event = db["events"][0]
    logs = event.get("logs") or []
    assert any(log.get("actor") == "smart_shortcuts" for log in logs)


def test_happy_path_step3_to_4_hil_gate(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "step3_hil.json"
    mapping = _stub_agent

    result = _run(
        db_path,
        mapping,
        "m1",
        "We'd like to book Room A on 20.05.2025 for 18 people.",
        info={
            "date": "2025-05-20",
            "start_time": "09:00",
            "end_time": "17:00",
            "participants": 18,
            "room": "Room A",
        },
    )
    if result["action"] == "date_confirmed":
        result = _run(
            db_path,
            mapping,
            "m1-follow",
            "Checking availability.",
        )
    assert result["action"] == "room_avail_result"
    event = _event(db_path)
    assert event["current_step"] == 3
    assert event.get("room_pending_decision")
    assert event["locked_room_id"] is None
    pending_room = event["room_pending_decision"].get("selected_room")

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
    assert event["locked_room_id"] == pending_room
    assert event["room_eval_hash"] == event["requirements_hash"]
    audit_pairs = {(entry["from_step"], entry["to_step"], entry["reason"]) for entry in event["audit"]}
    assert (3, 4, "room_hil_approved") in audit_pairs
