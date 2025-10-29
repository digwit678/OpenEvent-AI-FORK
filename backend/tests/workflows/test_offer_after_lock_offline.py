from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflow_email import load_db, process_msg


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODE", "stub")
    monkeypatch.setenv("OPENAI_TEST_MODE", "1")
    monkeypatch.setenv("NO_UNSOLICITED_MENUS", "true")
    monkeypatch.setenv("PRODUCT_FLOW_ENABLED", "true")
    monkeypatch.setenv("EVENT_SCOPED_UPSELL", "true")
    monkeypatch.setenv("CAPTURE_BUDGET_ON_HIL", "true")
    monkeypatch.setenv("DISABLE_MANUAL_REVIEW_FOR_TESTS", "true")
    monkeypatch.setenv("TZ", "Europe/Zurich")
    # Ensure auto-lock is off for policy tests
    monkeypatch.setenv("ALLOW_AUTO_ROOM_LOCK", "false")
    # Reset the adapter in case other tests already set it
    from backend.workflows.llm import adapter as llm_adapter

    llm_adapter.reset_llm_adapter()


def _msg(body: str, *, msg_id: str) -> Dict[str, str]:
    return {
        "msg_id": msg_id,
        "from_name": "Taylor Client",
        "from_email": "taylor@example.com",
        "subject": "Workshop booking",
        "ts": "2025-11-01T09:00:00Z",
        "body": body,
    }


def _process(db_path: Path, *, msg_id: str, body: str) -> Dict[str, Any]:
    return process_msg(_msg(body, msg_id=msg_id), db_path=db_path)


def _load_event(db_path: Path) -> Dict[str, Any]:
    db = load_db(db_path)
    assert db.get("events"), "expected at least one event"
    return db["events"][0]


def _patch_user_info(monkeypatch: pytest.MonkeyPatch, mapping: Dict[str, Dict[str, Any]]) -> None:
    from backend.workflows.llm import adapter as llm_adapter

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    if hasattr(llm_adapter.adapter, "extract_user_information"):
        monkeypatch.setattr(llm_adapter.adapter, "extract_user_information", fake_extract, raising=False)
    else:
        monkeypatch.setattr(llm_adapter.adapter, "extract_entities", fake_extract, raising=False)


def test_offline_no_auto_lock_and_explicit_lock_then_offer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "offline-offer.json"
    # Step 1: Provide date/time and basic requirements deterministically via stub mapping
    _patch_user_info(
        monkeypatch,
        {
            "m1": {"date": "2025-11-02", "start_time": "18:00", "end_time": "22:00", "participants": 15},
        },
    )
    first = _process(db_path, msg_id="m1", body="Need 18:00–22:00 slots in early November for 15 people.")
    # Step 2/3 turn: confirm date explicitly
    _patch_user_info(
        monkeypatch,
        {
            "m2": {"event_date": "02.11.2025", "start_time": "18:00", "end_time": "22:00"},
        },
    )
    second = _process(db_path, msg_id="m2", body="Take 2025-11-02 18:00–22:00 for the workshop.")
    assert second["action"] != "offer_draft_prepared", "Offer must not be prepared before a lock"
    ev = _load_event(db_path)
    assert ev.get("locked_room_id") in (None, ""), "Room should not be locked before explicit instruction"
    assert not (ev.get("offers") or []), "Offer must not be generated before a lock"

    # Step 3: Explicit lock
    lock = _process(db_path, msg_id="m3", body="Please lock Room A for us.")
    assert lock["action"] in {"room_auto_locked", "room_lock_retained"}
    locked = _load_event(db_path)
    assert locked.get("locked_room_id") == "Room A"
    assert locked.get("current_step") == 4

    # Step 4: Prepare offer upon request and ensure it doesn't detour to availability
    offer = _process(db_path, msg_id="m4", body="Great, please send over the offer draft.")
    assert offer["action"] == "offer_draft_prepared"


def test_offline_no_auto_lock_when_flag_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "offline-policy.json"
    _patch_user_info(
        monkeypatch,
        {
            "p1": {"date": "2025-11-02", "start_time": "18:00", "end_time": "22:00", "participants": 15},
        },
    )
    _process(db_path, msg_id="p1", body="Need 18:00–22:00 slots in early November for 15 people.")
    _patch_user_info(
        monkeypatch,
        {
            "p2": {"event_date": "02.11.2025", "start_time": "18:00", "end_time": "22:00"},
        },
    )
    _process(db_path, msg_id="p2", body="Take 2025-11-02 18:00–22:00 option.")
    ev = _load_event(db_path)
    assert ev.get("locked_room_id") in (None, ""), "Must not auto-lock with flag=false"
    decision = (ev.get("room_decision") or {}).get("status", "").lower()
    assert decision != "locked"


def test_offline_explicit_lock_is_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "offline-explicit.json"
    _patch_user_info(
        monkeypatch,
        {
            "e1": {"date": "2025-11-02", "start_time": "18:00", "end_time": "22:00", "participants": 15, "room": "Room B"},
        },
    )
    _process(db_path, msg_id="e1", body="Preferred room Room B; need 18:00–22:00 in early November.")
    _patch_user_info(
        monkeypatch,
        {
            "e2": {"event_date": "02.11.2025", "start_time": "18:00", "end_time": "22:00"},
        },
    )
    _process(db_path, msg_id="e2", body="Confirm 2025-11-02 18:00–22:00.")
    ev = _load_event(db_path)
    assert ev.get("locked_room_id") in (None, ""), "Preferred room must not auto-lock with flag=false"
    _process(db_path, msg_id="e3", body="Please lock Room B for us.")
    final_ev = _load_event(db_path)
    assert final_ev.get("locked_room_id") == "Room B"


def test_offline_offer_request_after_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "offline-offer-route.json"
    _patch_user_info(
        monkeypatch,
        {
            "r1": {"date": "2025-11-02", "start_time": "18:00", "end_time": "22:00", "participants": 15},
            "r2": {"event_date": "02.11.2025", "start_time": "18:00", "end_time": "22:00"},
        },
    )
    _process(db_path, msg_id="r1", body="Need 18:00–22:00 in early November.")
    _process(db_path, msg_id="r2", body="Take 2025-11-02 18:00–22:00.")
    _process(db_path, msg_id="r3", body="Lock Room A for that date.")
    ev = _load_event(db_path)
    assert ev.get("locked_room_id") == "Room A"
    assert ev.get("current_step") == 4
    attempt = _process(db_path, msg_id="r4", body="Please send the offer draft.")
    assert attempt.get("action") == "offer_draft_prepared"
