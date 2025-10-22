import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.adapters.agent_adapter import get_agent_adapter  # noqa: E402
from backend.domain import EventStatus, TaskType  # noqa: E402
from backend.workflow_email import load_db, process_msg, save_db  # noqa: E402
from backend.workflows.io.database import load_rooms  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("OE_SKIP_TESTS", "1") == "1",
    reason="Skipping in constrained env; set OE_SKIP_TESTS=0 to run.",
)


@pytest.fixture(autouse=True)
def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["AGENT_MODE"] = "stub"
    from backend.workflows.llm import adapter as llm_adapter

    llm_adapter.adapter = get_agent_adapter()


def _message(body: str, *, msg_id: str, subject: str = "Event request", email: str = "client@example.com") -> Dict[str, Any]:
    return {
        "msg_id": msg_id,
        "from_name": "Alex Client",
        "from_email": email,
        "subject": subject,
        "ts": "2025-01-01T09:00:00Z",
        "body": body,
    }


def _load_event(db_path: Path) -> Dict[str, Any]:
    db = load_db(db_path)
    assert db["events"], "Expected at least one event in DB."
    return db["events"][0]


def _populate_room_status(
    db_path: Path,
    event_date: str,
    status: EventStatus,
    rooms: List[str],
) -> None:
    db = load_db(db_path)
    for room_name in rooms:
        db["events"].append(
            {
                "event_id": f"block-{room_name}",
                "created_at": "2025-01-01T10:00:00Z",
                "status": status.value,
                "current_step": 7,
                "caller_step": None,
                "thread_state": "Closed",
                "chosen_date": event_date,
                "date_confirmed": True,
                "locked_room_id": room_name,
                "requirements": {},
                "requirements_hash": None,
                "room_eval_hash": None,
                "offer_id": None,
                "audit": [],
                "event_data": {
                    "Status": status.value,
                    "Event Date": event_date,
                    "Preferred Room": room_name,
                    "Email": f"{room_name.lower().replace(' ', '')}@example.com",
                },
                "msgs": [],
            }
        )
    save_db(db, db_path)


def test_intake_guard_manual_review(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    msg = _message("Hello team,\nJust saying hi.", msg_id="m1", subject="Hello")

    result = process_msg(msg, db_path=db_path)
    db = load_db(db_path)

    assert result["action"] == "manual_review_enqueued"
    assert not db["events"]
    assert db["tasks"], "Expected a manual review task to be enqueued."
    assert db["tasks"][0]["type"] == TaskType.MANUAL_REVIEW.value
    assert result["draft_messages"]
    assert all(draft["requires_approval"] for draft in result["draft_messages"])
    assert result["thread_state"] == "In Progress"


def test_step2_five_date_loop_and_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"

    initial = _message(
        (
            "Hello,\n"
            "We would like to host a workshop for about 20 people at your venue.\n"
            "Could you share available dates?\n"
        ),
        msg_id="m1",
    )
    result1 = process_msg(initial, db_path=db_path)

    assert result1["action"] == "date_options_proposed"
    assert result1["thread_state"] == "Awaiting Client Response"
    assert result1["draft_messages"]
    draft_topics = {draft["topic"] for draft in result1["draft_messages"]}
    assert "date_candidates" in draft_topics
    candidate_dates = result1.get("candidate_dates") or []
    assert 0 < len(candidate_dates) <= 5

    event = _load_event(db_path)
    assert event["current_step"] == 2
    assert event["date_confirmed"] is False
    assert event["thread_state"] == "Awaiting Client Response"

    confirmation = _message(
        "Thanks! Let's confirm 15.03.2025 for the workshop.",
        msg_id="m2",
    )
    result2 = process_msg(confirmation, db_path=db_path)

    assert result2["action"] == "room_avail_result"
    # Step 2 confirmation draft is still present before Step 3 additions.
    topics = {draft["topic"] for draft in result2["draft_messages"]}
    assert "date_confirmation" in topics
    assert all(draft["requires_approval"] for draft in result2["draft_messages"])

    event_after = _load_event(db_path)
    assert event_after["date_confirmed"] is True
    assert event_after["chosen_date"] == "15.03.2025"
    assert event_after["current_step"] in {3, 4}
    assert any(entry["to_step"] == 3 for entry in event_after["audit"])


def test_step3_entry_guard_skips_when_cached(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"

    # Create event and confirm date.
    process_msg(
        _message(
            "We'd like to plan a workshop for 18 participants. Can you share dates?",
            msg_id="m1",
        ),
        db_path=db_path,
    )
    process_msg(
        _message("Please confirm 20.04.2025 for the workshop.", msg_id="m2"),
        db_path=db_path,
    )
    result3 = process_msg(
        _message(
            "Room A would be perfect for 18 people in workshop layout.",
            msg_id="m3",
        ),
        db_path=db_path,
    )
    assert result3["action"] == "room_avail_result"

    event = _load_event(db_path)
    baseline_hash = event["room_eval_hash"]
    assert baseline_hash
    assert event["locked_room_id"] is not None

    # No changes -> should skip evaluation.
    result4 = process_msg(
        _message("Just checking our Room A workshop for 18 people is on track.", msg_id="m4"),
        db_path=db_path,
    )
    assert result4["action"] == "room_eval_skipped"
    assert result4.get("cached") is True
    event_after = _load_event(db_path)
    assert event_after["room_eval_hash"] == baseline_hash


@pytest.mark.parametrize(
    "scenario, setup_fn, expected_status",
    [
        ("unavailable", "block_confirmed", "Unavailable"),
        ("available", "none", "Available"),
        ("option", "block_option", "Option"),
    ],
)
def test_step3_outcomes_and_persistence(tmp_path: Path, scenario: str, setup_fn: str, expected_status: str) -> None:
    db_path = tmp_path / f"{scenario}.json"

    initial_body = (
        "Hello, we need Room A for 24 participants. Could you share dates?"
        if expected_status != "Available"
        else "Hello, we need a space for 24 participants. Could you share dates?"
    )
    process_msg(
        _message(initial_body, msg_id="m1"),
        db_path=db_path,
    )

    if setup_fn == "block_confirmed":
        _populate_room_status(
            db_path,
            "15.03.2025",
            EventStatus.CONFIRMED,
            list(load_rooms()),
        )
    elif setup_fn == "block_option":
        _populate_room_status(db_path, "15.03.2025", EventStatus.OPTION, ["Room A"])

    confirmation_body = (
        "Let's confirm 15.03.2025 and keep Room A."
        if expected_status != "Available"
        else "Let's confirm 15.03.2025 for the workshop."
    )
    result = process_msg(
        _message(confirmation_body, msg_id="m2"),
        db_path=db_path,
    )

    assert result["action"] == "room_avail_result"
    assert result["selected_status"] == expected_status
    event = _load_event(db_path)
    req_hash = event["requirements_hash"]

    if expected_status in {"Available", "Option"}:
        assert event["locked_room_id"] == "Room A"
        assert event["room_eval_hash"] == req_hash
    else:
        assert event["locked_room_id"] is None
        assert event["room_eval_hash"] == req_hash

    topics = {draft["topic"] for draft in result["draft_messages"]}
    expected_topic = {
        "Unavailable": "room_unavailable",
        "Available": "room_available",
        "Option": "room_option",
    }[expected_status]
    assert expected_topic in topics
    assert all(draft["requires_approval"] for draft in result["draft_messages"])


def test_detour_to_step2_on_new_date_from_step3(tmp_path: Path) -> None:
    db_path = tmp_path / "detour.json"
    process_msg(
        _message(
            "Planning a session for 12 people. Could you share available dates?",
            msg_id="m1",
        ),
        db_path=db_path,
    )
    process_msg(
        _message("Confirm the date 10.05.2025 please.", msg_id="m2"),
        db_path=db_path,
    )
    process_msg(
        _message("Room B seems ideal for us.", msg_id="m3"),
        db_path=db_path,
    )

    detour_result = process_msg(
        _message("We need to move to 24.05.2025 instead.", msg_id="m4"),
        db_path=db_path,
    )

    assert detour_result["action"] == "room_avail_result"
    event = _load_event(db_path)
    assert event["chosen_date"] == "24.05.2025"
    assert event["room_eval_hash"] is not None
    audit_pairs = {(entry["from_step"], entry["to_step"]) for entry in event["audit"]}
    assert (3, 2) in audit_pairs
    assert (2, 3) in audit_pairs


def test_requirement_change_triggers_step3_detour(tmp_path: Path) -> None:
    db_path = tmp_path / "requirements.json"

    process_msg(
        _message(
            "We'd like a workshop for 10 people. Could you share dates?",
            msg_id="m1",
        ),
        db_path=db_path,
    )
    process_msg(
        _message("Confirm 12.06.2025 for the workshop.", msg_id="m2"),
        db_path=db_path,
    )
    process_msg(
        _message("Room C would be great.", msg_id="m3"),
        db_path=db_path,
    )

    db = load_db(db_path)
    event = db["events"][0]
    event["current_step"] = 4
    event["caller_step"] = None
    save_db(db, db_path)

    result = process_msg(
        _message(
            "We now expect around 30 people. Please adjust the reservation.",
            msg_id="m4",
        ),
        db_path=db_path,
    )

    assert result["action"] == "room_avail_result"
    event_after = _load_event(db_path)
    assert event_after["current_step"] == 4
    assert event_after["caller_step"] is None
    assert event_after["room_eval_hash"] == event_after["requirements_hash"]
    audit_steps = {(entry["from_step"], entry["to_step"]) for entry in event_after["audit"]}
    assert (4, 3) in audit_steps
    assert (3, 4) in audit_steps


def test_hil_gates_and_thread_state_transitions(tmp_path: Path) -> None:
    db_path = tmp_path / "hil.json"

    result1 = process_msg(
        _message(
            "Hello, we want to plan a team offsite for 16 people. Could you share available dates?",
            msg_id="m1",
        ),
        db_path=db_path,
    )
    assert result1["thread_state"] == "Awaiting Client Response"
    assert all(draft["requires_approval"] for draft in result1["draft_messages"])

    result2 = process_msg(
        _message("Confirm 04.07.2025 works perfectly.", msg_id="m2"),
        db_path=db_path,
    )
    assert result2["thread_state"] == "Awaiting Client Response"
    assert all(draft["requires_approval"] for draft in result2["draft_messages"])

    event = _load_event(db_path)
    assert event["audit"], "Expected audit entries to be recorded."
