import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.domain import EventStatus  # noqa: E402
from backend.workflow_email import load_db, process_msg, save_db  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Dict[str, Any]]:
    os.environ["AGENT_MODE"] = "stub"
    from backend.workflows.llm import adapter as llm_adapter

    mapping: Dict[str, Dict[str, Any]] = {}

    def fake_extract(payload: Dict[str, Any]) -> Dict[str, Any]:
        return mapping.get(payload.get("msg_id"), {})

    if hasattr(llm_adapter.adapter, "extract_user_information"):
        monkeypatch.setattr(llm_adapter.adapter, "extract_user_information", fake_extract, raising=False)
    else:
        monkeypatch.setattr(llm_adapter.adapter, "extract_entities", fake_extract, raising=False)
    return mapping


def _message(body: str, *, msg_id: str, subject: str = "Event request") -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Test Client",
        "from_email": "client@example.com",
        "subject": subject,
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
    assert db["events"], "Expected event to exist"
    return db["events"][0]


def _bootstrap_to_offer(db_path: Path, mapping: Dict[str, Dict[str, Any]]) -> None:
    res1 = _run(
        db_path,
        mapping,
        "lead",
        "Hello, we need a room for 20 people.",
        info={"date": "2025-09-10", "participants": 20, "room": "Room A"},
    )
    assert res1["action"] == "room_avail_result"
    event = _event(db_path)
    assert event["current_step"] == 3
    mapping["hil-room"] = {"hil_approve_step": 3}
    res2 = _run(db_path, mapping, "hil-room", "HIL approval for room", info={"hil_approve_step": 3})
    assert res2["action"] == "offer_draft_prepared"
    event = _event(db_path)
    assert event["current_step"] == 5
    assert event["caller_step"] is None
    assert event["thread_state"] == "Awaiting Client Response"


def _accept_offer(db_path: Path, mapping: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    result = _run(db_path, mapping, "accept", "We accept the offer as is.")
    event = _event(db_path)
    assert event["current_step"] in {6, 7}
    return result


def _hil_confirm(db_path: Path, mapping: Dict[str, Dict[str, Any]], kind: str = "final") -> Dict[str, Any]:
    return _run(db_path, mapping, f"hil-{kind}", "HIL approval", info={"hil_approve_step": 7})


# ---------------------------------------------------------------------------
# Step 4 — Offer lifecycle
# ---------------------------------------------------------------------------


def test_s4_offer_lifecycle(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s4.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    event = _event(db_path)
    assert event["locked_room_id"] == "Room A"
    assert event["room_eval_hash"] == event["requirements_hash"]

    res = _run(
        db_path,
        mapping,
        "add-products",
        "Could you add a lunch menu as well?",
        info={"products_add": [{"name": "Lunch Menu", "quantity": 20, "unit_price": 45.0}]},
    )
    assert res["action"] == "offer_draft_prepared"
    event = _event(db_path)
    assert event["offers"][-1]["version"] == 2
    assert event["offers"][-2]["status"] == "Superseded"
    assert event["caller_step"] is None
    audit_pairs = {(entry["from_step"], entry["to_step"], entry["reason"]) for entry in event["audit"]}
    assert (4, 5, "return_to_caller") in audit_pairs


# ---------------------------------------------------------------------------
# Step 5 — Negotiation behaviours
# ---------------------------------------------------------------------------


def test_s5_counters_bound(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s5-counter.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)

    for idx in range(3):
        res = _run(
            db_path,
            mapping,
            f"counter-{idx}",
            "Could you lower the price a little?",
            info={"offer_total_override": 800.0 - idx * 10},
        )
        assert res["action"] == "offer_draft_prepared"

    res = _run(
        db_path,
        mapping,
        "counter-final",
        "Any chance of a further discount?",
        info={"offer_total_override": 750.0},
    )
    assert res["action"] == "negotiation_manual_review"
    event = _event(db_path)
    assert event["negotiation_state"]["counter_count"] == 4
    assert event["offer_sequence"] == 4


def test_s5_structural_detour_and_return(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s5-struct.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)

    res = _run(
        db_path,
        mapping,
        "struct-change",
        "We now expect 28 participants.",
        info={"participants": 28},
    )
    assert res["action"] in {"negotiation_detour", "room_avail_result"}
    event = _event(db_path)
    assert event["current_step"] == 3
    assert event["caller_step"] == 5

    mapping["struct-room"] = {"room": "Room A"}
    res_room = _run(db_path, mapping, "struct-room", "Room A still works for us.")
    assert res_room["action"] == "room_avail_result"
    res_hil = _run(db_path, mapping, "struct-hil", "HIL approves updated room", info={"hil_approve_step": 3})
    assert res_hil["action"] == "offer_draft_prepared"
    event = _event(db_path)
    assert event["current_step"] == 5
    assert event["caller_step"] is None
    audit_pairs = {(entry["from_step"], entry["to_step"], entry["reason"]) for entry in event["audit"]}
    assert any(
        step_from == 5
        and step_to == 3
        and reason in {"negotiation_changed_participants", "requirements_updated"}
        for step_from, step_to, reason in audit_pairs
    )
    assert (4, 5, "return_to_caller") in audit_pairs


# ---------------------------------------------------------------------------
# Step 6 — Transition checkpoint
# ---------------------------------------------------------------------------


def test_s6_transition_checkpoint(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s6.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    event = _event(db_path)
    db = load_db(db_path)
    db["events"][0]["locked_room_id"] = None  # force a blocker
    save_db(db, db_path)

    res_accept = _run(db_path, mapping, "accept", "We accept the offer as presented.")
    assert res_accept["action"] == "transition_blocked"
    event = _event(db_path)
    assert event["current_step"] == 6
    assert event["thread_state"] == "Awaiting Client Response"

    db = load_db(db_path)
    db["events"][0]["locked_room_id"] = "Room A"
    db["events"][0]["room_eval_hash"] = db["events"][0]["requirements_hash"]
    save_db(db, db_path)
    res_retry = _run(db_path, mapping, "retry", "Providing requested confirmation info.")
    assert res_retry["action"] == "transition_ready"
    event = _event(db_path)
    assert event["current_step"] == 7
    audit_pairs = {(entry["from_step"], entry["to_step"], entry["reason"]) for entry in event["audit"]}
    assert (6, 7, "transition_ready") in audit_pairs


# ---------------------------------------------------------------------------
# Step 7 — Confirmation scenarios
# ---------------------------------------------------------------------------


def test_s7_confirm(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s7-confirm.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    _accept_offer(db_path, mapping)

    confirm = _run(db_path, mapping, "confirm", "Please confirm the booking.")
    assert confirm["action"] == "confirmation_draft"
    event = _event(db_path)
    assert event["confirmation_state"]["pending"] == {"kind": "final_confirmation"}

    final = _hil_confirm(db_path, mapping)
    assert final["action"] == "confirmation_finalized"
    event = _event(db_path)
    assert event["event_data"]["Status"] == EventStatus.CONFIRMED.value
    assert event["calendar_blocks"], "Expected a calendar block"


def test_s7_reserve_deposit(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s7-deposit.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    _accept_offer(db_path, mapping)
    db = load_db(db_path)
    db["events"][0]["deposit_state"] = {"required": True, "percent": 30, "status": "required", "due_amount": 450.0}
    save_db(db, db_path)

    pending = _run(db_path, mapping, "deposit-request", "We confirm and will pay the deposit soon.")
    assert pending["action"] == "confirmation_deposit_requested"
    event = _event(db_path)
    assert event["deposit_state"]["status"] == "requested"

    paid = _run(db_path, mapping, "deposit-paid", "Deposit has been paid today.")
    assert paid["action"] == "confirmation_draft"
    event = _event(db_path)
    assert event["deposit_state"]["status"] == "paid"

    final = _hil_confirm(db_path, mapping)
    assert final["action"] == "confirmation_finalized"
    event = _event(db_path)
    assert event["event_data"]["Status"] == EventStatus.CONFIRMED.value


def test_s7_site_visit(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s7-visit.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    _accept_offer(db_path, mapping)

    result = _run(db_path, mapping, "site-visit", "Can we schedule a site visit?")
    assert result["action"] == "confirmation_site_visit"
    event = _event(db_path)
    visit_state = event.get("site_visit_state")
    assert visit_state and visit_state["status"] == "proposed" and visit_state["proposed_slots"]

    sent = _hil_confirm(db_path, mapping, kind="visit")
    assert sent["action"] == "confirmation_site_visit_sent"
    event = _event(db_path)
    assert event["thread_state"] == "Awaiting Client Response"


def test_s7_change_decline_question(tmp_path: Path, _stub_agent: Dict[str, Dict[str, Any]]) -> None:
    db_path = tmp_path / "s7-change.json"
    mapping = _stub_agent

    _bootstrap_to_offer(db_path, mapping)
    _accept_offer(db_path, mapping)

    change = _run(
        db_path,
        mapping,
        "change",
        "Could we change to 30 attendees?",
        info={"participants": 30},
    )
    assert change["action"] in {"confirmation_detour", "room_avail_result"}
    event = _event(db_path)
    assert event["caller_step"] == 7

    mapping["change-room"] = {"room": "Room A"}
    _run(db_path, mapping, "change-room", "Room A still fine.")
    _run(db_path, mapping, "change-hil", "HIL approves", info={"hil_approve_step": 3})
    event = _event(db_path)
    assert event["caller_step"] is None

    decline = _run(db_path, mapping, "decline", "We have to cancel the booking.")
    assert decline["action"] == "confirmation_decline"
    final_decline = _hil_confirm(db_path, mapping, kind="decline")
    assert final_decline["action"] == "confirmation_decline_sent"

    question = _run(db_path, mapping, "question", "Could you help with parking details?")
    assert question["action"] == "confirmation_question"
    event = _event(db_path)
    assert event["thread_state"] == "Awaiting Client Response"
