"""Behavioural tests that ensure workflow prompts follow the Workflow v3 copy."""

from __future__ import annotations

import datetime as dt
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflow_email import load_db, process_msg, save_db
from backend.workflows.common.gatekeeper import explain_step7_gate
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.groups.event_confirmation.trigger.process import _base_payload
from backend.workflows.planner import maybe_run_smart_shortcuts


@pytest.fixture(autouse=True)
def _force_stub_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic stub adapter for repeatable expectations."""

    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("INTENT_FORCE_EVENT_REQUEST", "1")
    from backend.workflows.llm import adapter as llm_adapter

    llm_adapter.reset_llm_adapter()


@pytest.fixture
def _stub_mapping(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Dict[str, Any]]:
    from backend.workflows.llm import adapter as llm_adapter

    mapping: Dict[str, Dict[str, Any]] = {}

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    if hasattr(llm_adapter.adapter, "extract_user_information"):
        monkeypatch.setattr(llm_adapter.adapter, "extract_user_information", fake_extract, raising=False)
    else:
        monkeypatch.setattr(llm_adapter.adapter, "extract_entities", fake_extract, raising=False)
    return mapping


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
            "from_name": "Taylor Client",
            "from_email": "taylor@example.com",
            "subject": "Event inquiry",
            "ts": "2025-01-10T09:00:00Z",
            "body": body,
        }
    )
    state = WorkflowState(message=message, db_path=db_path, db=db)
    state.event_entry = event
    state.event_id = event.get("event_id")
    state.client_id = event.get("client_id") or "taylor@example.com"
    state.client = {"email": "taylor@example.com"}
    state.user_info = user_info
    state.current_step = event.get("current_step")
    result = maybe_run_smart_shortcuts(state)
    assert result is not None, "Smart shortcuts did not run"
    payload = result.merged() if hasattr(result, "merged") else result
    payload.setdefault("action", "smart_shortcut_processed")
    save_db(state.db, db_path)
    return payload


def _draft_by_topic(drafts: List[Dict[str, str]], topic: str) -> Dict[str, str]:
    for draft in drafts:
        if draft.get("topic") == topic:
            return draft
    raise AssertionError(f"Draft with topic '{topic}' not found. Available: {[d.get('topic') for d in drafts]}")


def _set_manager_items(db_path: Path, items: List[Dict[str, str]]) -> None:
    db = load_db(db_path)
    event = db["events"][0]
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
    state["manager_added_items"] = items
    event["current_step"] = 2
    save_db(db, db_path)


def _prepare_event_with_manager_items(
    db_path: Path,
    mapping: Dict[str, Dict[str, Any]],
    items: List[Dict[str, str]],
) -> str:
    _run(
        db_path,
        mapping,
        "setup",
        "Hello, we need date options in April.",
        info={"date": "2026-04-10", "start_time": "18:00", "end_time": "22:00"},
    )
    _set_manager_items(db_path, items)
    db = load_db(db_path)
    event = db["events"][0]
    event.setdefault("requirements", {})["number_of_participants"] = 20
    event["requirements_hash"] = requirements_hash(event["requirements"])
    event["room_pending_decision"] = {
        "selected_room": "Room B",
        "selected_status": "Available",
        "requirements_hash": event["requirements_hash"],
    }
    event["locked_room_id"] = "Room B"
    save_db(db, db_path)
    return event["event_id"]


def _ready_confirmation_event() -> Dict[str, Any]:
    return {
        "event_id": "evt-123",
        "current_step": 7,
        "date_confirmed": True,
        "locked_room_id": "Room A",
        "offer_status": "Accepted",
        "event_data": {
            "Company": "Acme GmbH",
            "Billing Address": "Acme GmbH\nSamplestrasse 1\n8000 Zürich\nSwitzerland",
        },
        "requested_window": {
            "start": "18:00",
            "end": "22:00",
            "tz": "Europe/Zurich",
        },
    }


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
    date_prompt = _draft_by_topic(first_result["draft_messages"], "date_candidates")["body"]
    assert date_prompt.startswith("AVAILABLE DATES:")
    assert "NEXT STEP:" in date_prompt

    second_result = process_msg(
        _message(
            "Let’s lock the 15th of March 2025 for around 60 guests in Room B.",
            msg_id="m2",
        ),
        db_path=db_path,
    )

    assert second_result["action"] == "date_time_clarification"

    drafts = second_result["draft_messages"]
    clarification_copy = _draft_by_topic(drafts, "date_time_clarification")["body"]
    assert clarification_copy.startswith("Noted 15.03.2025")
    assert "Preferred time" in clarification_copy

    event_entry = load_db(db_path)["events"][0]
    assert event_entry.get("chosen_date") == "15.03.2025"
    assert event_entry.get("requirements", {}).get("number_of_participants") == 60
    assert event_entry.get("locked_room_id") is None


def test_infer_date_from_body_handles_ordinals(_frozen_today: None) -> None:
    """Directly exercise the ordinal regex fallback used in stub mode."""

    from backend.workflows.llm import adapter as llm_adapter

    inferred = llm_adapter._infer_date_from_body("Could we meet on the 3rd of April?")
    assert inferred == "2025-04-03"


def test_answer_first_dates_no_menus_in_intake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    result = process_msg(
        _message("Hi team, can you share available dates in April?"),
        db_path=tmp_path / "no-menus.json",
    )
    assert result["action"] == "smart_shortcut_processed"
    body = result["message"].lower()
    assert "menu" not in body
    assert "catering" not in body
    assert result.get("answered_question_first") is True


def test_preask_interest_before_any_menus(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "upsell.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "av", "name": "Projector"},
            {"class": "furniture", "name": "Bar Tables"},
        ],
    )

    result = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
            "participants": 24,
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )
    result_payload = result.merged() if hasattr(result, "merged") else result
    assert result_payload["action"] == "smart_shortcut_processed"
    message = result_payload["message"]
    assert "Add-ons (optional)" not in message
    assert "Would you like to see catering options" in message
    assert "Would you like to see AV add-ons" in message
    assert "Bar Tables" not in message  # limited to two prompts
    assert "1." not in message
    assert result_payload["menus_included"] == "false"
    assert result_payload["menus_phase"] == "post_room"
    assert result_payload["room_checked"] is True
    assert "catering" in (result_payload.get("preask_shown") or [])
    assert result_payload["preask_response"].get("catering") == "n/a"


def test_explicit_user_requests_menus_allows_menu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    result = process_msg(
        _message("Could you send me the catering menu options?"),
        db_path=tmp_path / "menus.json",
    )

    assert result["action"] == "smart_shortcut_processed"
    message_lower = result["message"].lower()
    assert "which date should i check for you" in message_lower
    assert "add-ons (optional)" not in message_lower
    assert result["menus_included"] == "false"
    assert result["menus_phase"] == "pre_room_blocked"


def test_preask_yes_shows_compact_preview_max3_no_prices(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "preask-yes.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "catering", "name": "Lunch Buffet"},
            {"class": "catering", "name": "Gourmet Tapas"},
            {"class": "catering", "name": "Seasonal Desserts"},
        ],
    )
    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
            "participants": 24,
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )

    preview = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m3",
        body="Yes, catering options please.",
    )
    preview_payload = preview.merged() if hasattr(preview, "merged") else preview
    assert preview_payload["action"] == "smart_shortcut_processed"
    assert preview_payload["menus_included"] == "preview"
    assert preview_payload["preview_class_shown"] == "catering"
    numbered = [
        line.strip()
        for line in preview_payload["message"].splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    assert 'Which one (1–3) or "show more"?' in preview_payload["message"]
    assert 1 <= len(numbered) <= 3
    assert all("CHF" not in line for line in numbered)
    assert preview_payload["preview_items_count"] == len(numbered)
    assert preview_payload["preask_response"].get("catering") == "yes"
    telemetry = preview_payload.get("telemetry") or {}
    assert telemetry.get("choice_context_active") is True
    assert preview_payload.get("choice_context_active") is True


def test_preask_no_suppresses_future_prompts_for_class(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "preask-no.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "av", "name": "Projector"},
        ],
    )
    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
            "participants": 24,
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )

    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m3",
        body="No catering options please.",
    )

    follow_up = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m4",
        body="Any other suggestions?",
    )
    follow_payload = follow_up.merged() if hasattr(follow_up, "merged") else follow_up
    assert follow_payload["action"] == "smart_shortcut_processed"
    assert "catering options" not in follow_payload["message"].lower()
    assert follow_payload["preask_response"].get("catering") == "no"


def test_preask_rotation_max_two_classes_per_turn(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "preask-rotation.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "av", "name": "Projector"},
            {"class": "furniture", "name": "Bar Tables"},
        ],
    )
    result = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
            "participants": 24,
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )

    prompts = [line for line in result["message"].splitlines() if "Would you like to see" in line]
    assert len(prompts) == 2
    assert "furniture" not in " ".join(prompts).lower()
    shown = set(result.get("preask_shown") or [])
    assert shown == {"catering", "av"}


def test_preask_resets_if_item_set_changes_after_room_or_date_change(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "preask-reset.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "av", "name": "Projector"},
        ],
    )

    initial = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )
    initial_payload = initial.merged() if hasattr(initial, "merged") else initial
    assert "catering options" in initial_payload["message"]

    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m3",
        body="No catering options, thanks.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["products_state"]["manager_added_items"] = [
        {"class": "catering", "name": "Seasonal Desserts"},
        {"class": "av", "name": "PA System"},
    ]
    save_db(db, db_path)

    reset_prompt = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={"date": "2026-04-12"},
        msg_id="m4",
        body="We might shift to 12.04 instead.",
    )
    reset_payload = reset_prompt.merged() if hasattr(reset_prompt, "merged") else reset_prompt
    assert "Seasonal Desserts" not in reset_payload["message"]
    assert "Would you like to see catering options" in reset_payload["message"]
    candidates = set(reset_payload.get("preask_candidates") or [])
    assert {"catering", "av"}.issubset(candidates)


def test_choice_selection_ordinal_no_menu_redump(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "choice-ordinal.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "catering", "name": "Lunch Buffet"},
            {"class": "catering", "name": "Gourmet Tapas"},
        ],
    )
    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={
            "date": "2026-04-10",
            "start_time": "18:00",
            "end_time": "22:00",
            "room": "Room B",
        },
        msg_id="m2",
        body="Please confirm 10.04.2026 18-22 and lock Room B.",
    )
    _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m3",
        body="Yes, catering options please.",
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["choice_context"] = {
        "kind": "catering",
        "presented_at": "2025-01-10T09:00:00Z",
        "items": [
            {"idx": 1, "key": "c1", "label": "Coffee & Snacks", "value": {"name": "Coffee & Snacks"}},
            {
                "idx": 2,
                "key": "c2",
                "label": "Coffee & Snacks Deluxe",
                "value": {"name": "Coffee & Snacks Deluxe"},
            },
        ],
        "ttl_turns": 4,
        "lang": "en",
    }
    save_db(db, db_path)

    selection = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m4",
        body="Option 1 works for us.",
    )

    assert selection["action"] == "smart_shortcut_processed"
    assert "1." not in selection["message"]
    assert selection["selection_method"] == "ordinal"
    assert selection["choice_context_active"] is False
    assert selection["preask_response"].get("catering") in {"yes", "n/a"}
    db = load_db(db_path)
    event = db["events"][0]
    line_items = event["products_state"].get("line_items") or []
    assert any(item.get("name") == "Coffee & Tea" for item in line_items)


def test_choice_selection_ambiguous_prompts_one_clarification(
    tmp_path: Path,
    _stub_mapping: Dict[str, Dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMART_SHORTCUTS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")

    db_path = tmp_path / "choice-clarify.json"
    mapping = _stub_mapping
    event_id = _prepare_event_with_manager_items(
        db_path,
        mapping,
        [
            {"class": "catering", "name": "Coffee & Tea"},
            {"class": "catering", "name": "Lunch Buffet"},
        ],
    )
    db = load_db(db_path)
    event = next(evt for evt in db["events"] if evt.get("event_id") == event_id)
    event["choice_context"] = {
        "kind": "catering",
        "presented_at": "2025-01-10T09:00:00Z",
        "items": [
            {"idx": 1, "key": "c1", "label": "Coffee & Snacks", "value": {"name": "Coffee & Snacks"}},
            {
                "idx": 2,
                "key": "c2",
                "label": "Coffee & Snacks Deluxe",
                "value": {"name": "Coffee & Snacks Deluxe"},
            },
        ],
        "ttl_turns": 4,
        "lang": "en",
    }
    save_db(db, db_path)

    clarify = _invoke_shortcuts(
        db_path,
        event_id,
        user_info={},
        msg_id="m4",
        body="Coffee special sounds good.",
    )

    assert clarify["action"] == "smart_shortcut_processed"
    assert clarify["message"] == "Do you mean 1) Coffee & Snacks?"
    assert clarify["selection_method"] == "clarified"
    assert clarify["choice_context_active"] is True
    assert clarify["re_prompt_reason"] == "ambiguous"
    assert clarify["preask_response"].get("catering") == "clarify"
    db = load_db(db_path)
    persisted_context = next(evt for evt in db["events"] if evt.get("event_id") == event_id).get("choice_context")
    assert persisted_context is not None


def test_step7_gate_ready_enables_buttons(tmp_path: Path) -> None:
    event_entry = _ready_confirmation_event()
    state = WorkflowState(
        message=IncomingMessage.from_dict(_message("Step7 ready check", msg_id="gate-ready")),
        db_path=tmp_path / "gate.json",
        db={"events": []},
    )
    state.client_id = "taylor@example.com"
    payload = _base_payload(state, event_entry)
    gate = payload["gate_explain"]

    assert gate["ready"] is True
    assert gate["missing_now"] == []
    assert gate["reason"] == "ready"
    assert payload["buttons_rendered"] is True
    assert payload["buttons_enabled"] is True
    assert getattr(state.telemetry, "gate_explain") == gate


@pytest.mark.parametrize(
    ("mutator", "expected_missing"),
    [
        (lambda evt: evt.__setitem__("date_confirmed", False), "date_confirmed"),
        (lambda evt: evt.pop("locked_room_id", None), "locked_room_id"),
        (lambda evt: evt.__setitem__("offer_status", "Draft"), "offer_status"),
        (lambda evt: evt["event_data"].__setitem__("Company", ""), "billing.company"),
        (lambda evt: evt["event_data"].__setitem__("Billing Address", ""), "billing.address"),
    ],
)
def test_step7_gate_reports_missing_fields(mutator, expected_missing: str) -> None:
    event_entry = deepcopy(_ready_confirmation_event())
    mutator(event_entry)
    gate = explain_step7_gate(event_entry)

    assert gate["ready"] is False
    assert expected_missing in gate["missing_now"]
    assert gate["reason"] == expected_missing
