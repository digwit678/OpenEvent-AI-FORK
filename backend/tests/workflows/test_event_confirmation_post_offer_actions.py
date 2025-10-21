import json
import os
import sys
from pathlib import Path
from typing import Dict

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.domain import EventStatus, TaskStatus, TaskType  # noqa: E402
from backend.workflows.groups.event_confirmation.db_pers.post_offer import (  # noqa: E402
    HandlePostOfferRoute,
    HandleSiteVisitRoute,
    attach_post_offer_classification,
    enqueue_post_offer_routing_task,
    enqueue_site_visit_followup,
)
from backend.workflows.groups.offer.llm.client_reply_analysis import AnalyzeClientReply  # noqa: E402
from backend.workflows.io.database import get_default_db  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("OE_SKIP_TESTS", "1") == "1",
    reason="Skipping in constrained env; set OE_SKIP_TESTS=0 to run.",
)


def _make_event_entry(event_id: str, event_data: Dict[str, str]) -> Dict[str, object]:
    return {
        "event_id": event_id,
        "created_at": "2025-01-01T10:00:00Z",
        "event_data": dict(event_data),
        "msgs": [],
    }


def _base_event_data(**overrides: str) -> Dict[str, str]:
    data: Dict[str, str] = {
        "Status": EventStatus.LEAD.value,
        "Event Date": "15.03.2025",
        "Start Time": "14:00",
        "End Time": "16:00",
        "Preferred Room": "Room A",
        "Deposit": "none",
    }
    data.update({key: value for key, value in overrides.items() if value is not None})
    return data


def _bootstrap_env(message_text: str, client_email: str = "client@example.com") -> Dict[str, object]:
    db = get_default_db()
    event_id = "EVT-1"
    db["events"].append(_make_event_entry(event_id, _base_event_data()))
    event_entry = db["events"][0]
    event_data = event_entry["event_data"]
    db["clients"][client_email] = {
        "profile": {"name": "Client", "org": None, "phone": None},
        "history": [
            {
                "msg_id": "msg-1",
                "ts": "2025-01-01T09:00:00Z",
                "subject": "Re: Offer",
                "body_preview": "Preview",
                "intent": "client_reply",
                "confidence": 1.0,
                "user_info": {},
            }
        ],
        "event_ids": [event_id],
    }
    db["tasks"] = []

    analyzer = AnalyzeClientReply()
    classification = analyzer.run({"client_msg_text": message_text})["post_offer_classification"]
    attach_post_offer_classification(db, client_email, "msg-1", classification)
    task_id = enqueue_post_offer_routing_task(
        db,
        client_email,
        event_id,
        "msg-1",
        classification["response_type"],
    )
    return {
        "db": db,
        "event_id": event_id,
        "event_data": event_data,
        "task_id": task_id,
        "classification": classification,
        "client_email": client_email,
    }


def _history_tail(db: Dict[str, object], client_email: str) -> Dict[str, object]:
    history = db["clients"][client_email]["history"]
    return history[-1]


def _empty_site_visit_classification() -> Dict[str, object]:
    return {
        "response_type": "site_visit",
        "classification_confidence": 0.25,
        "classification_explanation": "acknowledgement",
        "extracted_fields": {
            "proposed_visit_datetimes": [],
            "mentions_deposit": False,
            "wants_to_pay_deposit_now": False,
            "requested_reserve_dates": [],
            "change_request_patch": {},
            "user_question_text": None,
        },
    }


def _setup_site_visit_task(tmp_path: Path, message_text: str) -> Dict[str, object]:
    env = _bootstrap_env(message_text)
    db = env["db"]

    post_handler = HandlePostOfferRoute()
    post_handler.run({"db": db, "task_id": env["task_id"]})

    site_task = next(task for task in db["tasks"] if task["type"] == TaskType.ROUTE_SITE_VISIT.value)
    calendar_dir = tmp_path / "calendar"
    calendar_dir.mkdir(parents=True, exist_ok=True)

    return {
        "db": db,
        "site_task_id": site_task["task_id"],
        "client_email": env["client_email"],
        "calendar_dir": calendar_dir,
        "event_id": env["event_id"],
    }


def test_confirm_branch_with_deposit_pending() -> None:
    env = _bootstrap_env("We confirm the booking.")
    db = env["db"]
    event_data = env["event_data"]
    event_data["Deposit"] = "required"
    event_data["Deposit Status"] = "pending"

    handler = HandlePostOfferRoute()
    result = handler.run({"db": db, "task_id": env["task_id"]})

    assert result["task_status"] == TaskStatus.DONE.value
    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "confirm: awaiting-deposit"
    assert "once the deposit arrives" in entry["message"]
    assert "Status: Option" in entry["message"]
    assert db["tasks"][0]["status"] == TaskStatus.DONE.value
    assert event_data["Status"] == EventStatus.OPTION.value


def test_confirm_branch_manager_pending_sets_pending_flag() -> None:
    env = _bootstrap_env("We confirm and are ready to proceed.")
    db = env["db"]
    event_data = env["event_data"]
    event_data["Deposit"] = "none"

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "confirm: pending-hil"
    assert "manager for a quick review" in entry["message"]
    assert event_data["Status"] == EventStatus.OPTION.value
    assert event_data["Manager Approval"] == "pending"


def test_confirm_branch_final_confirmation_when_manager_approved() -> None:
    env = _bootstrap_env("We confirm and everything is already approved.")
    db = env["db"]
    event_data = env["event_data"]
    event_data["Deposit"] = "none"
    event_data["Manager Approval"] = "approved"
    event_data["Status"] = EventStatus.OPTION.value

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "confirm: confirmed"
    assert "everything is confirmed" in entry["message"].lower()
    assert event_data["Status"] == EventStatus.CONFIRMED.value


def test_reserve_branch_sets_option_status() -> None:
    env = _bootstrap_env("Please hold the date for us.")
    db = env["db"]

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "reserve: option"
    assert "provisional option hold" in entry["message"].lower()
    assert env["event_data"]["Status"] == EventStatus.OPTION.value


def test_change_branch_summarises_patch() -> None:
    message = (
        "Could you change to 21.12.2025 starting 18:00, ending 22:00, and increase to 60 guests?"
    )
    env = _bootstrap_env(message)
    db = env["db"]

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "change: awaiting-decision"
    assert "i’ve noted the requested updates" in entry["message"].lower()
    assert "18:00" in entry["message"]
    assert env["event_data"]["Status"] == EventStatus.OPTION.value


def test_site_visit_branch_enqueues_pointer() -> None:
    message = "We'd like a tour on 2025-04-10 15:00 or 2025-04-11 11:15."
    env = _bootstrap_env(message)
    db = env["db"]

    handler = HandlePostOfferRoute()
    result = handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "visit: intake"
    assert "status:" in entry["message"].lower()

    site_tasks = [
        task for task in db["tasks"] if task["type"] == TaskType.ROUTE_SITE_VISIT.value
    ]
    assert len(site_tasks) == 1
    assert site_tasks[0]["status"] == TaskStatus.PENDING.value
    assert site_tasks[0]["payload"]["message_msg_id"] == "msg-1"
    assert result["created_tasks"] == [site_tasks[0]["task_id"]]
    assert env["event_data"]["Status"] == EventStatus.LEAD.value


def test_general_question_branch_includes_question_text() -> None:
    message = "Is the projector 4K and what's the ceiling height?"
    env = _bootstrap_env(message)
    db = env["db"]

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "question: acknowledgement"
    assert "projector 4K" in entry["message"]


def test_not_interested_branch_polite_closure() -> None:
    env = _bootstrap_env("Thanks but we'll cancel and go with another venue.")
    db = env["db"]

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "not-interested: closed"
    assert "If you change your mind" in entry["message"]
    assert env["event_data"]["Status"] == EventStatus.LEAD.value


def test_idempotent_processing_does_not_repeat_actions() -> None:
    env = _bootstrap_env("Please hold the date for us.")
    db = env["db"]

    handler = HandlePostOfferRoute()
    handler.run({"db": db, "task_id": env["task_id"]})
    history_count = len(db["clients"][env["client_email"]]["history"])

    result = handler.run({"db": db, "task_id": env["task_id"]})

    assert result["skipped"] is True
    assert len(db["clients"][env["client_email"]]["history"]) == history_count
    assert db["tasks"][0]["status"] == TaskStatus.DONE.value


def test_site_visit_booking_creates_hold_and_hil_task(tmp_path: Path) -> None:
    env = _setup_site_visit_task(tmp_path, "Let's do 2030-04-10 15:00 for the visit.")
    db = env["db"]
    handler = HandleSiteVisitRoute()

    handler.run({"db": db, "task_id": env["site_task_id"], "calendar_dir": env["calendar_dir"]})

    entry = _history_tail(db, env["client_email"])
    assert entry["note"] == "visit: option-pending-hil"
    hil_tasks = [task for task in db["tasks"] if task["type"] == TaskType.SITE_VISIT_HIL_REVIEW.value]
    assert len(hil_tasks) == 1
    assert hil_tasks[0]["status"] == TaskStatus.PENDING.value

    calendar_file = env["calendar_dir"] / "atelier-room-a.json"
    with calendar_file.open("r", encoding="utf-8") as handle:
        calendar_payload = json.load(handle)
    assert len(calendar_payload["busy"]) == 1
    hold = calendar_payload["busy"][0]
    assert hold["status"] == "option"
    assert hold["category"] == "site_visit"


def test_site_visit_busy_slots_offer_alternatives(tmp_path: Path) -> None:
    env = _setup_site_visit_task(tmp_path, "Could we visit on 2030-04-10 15:00?")
    busy_entry = {
        "start": "2030-04-10T14:30:00+02:00",
        "end": "2030-04-10T16:30:00+02:00",
        "description": "Existing booking",
    }
    calendar_file = env["calendar_dir"] / "atelier-room-a.json"
    with calendar_file.open("w", encoding="utf-8") as handle:
        json.dump({"busy": [busy_entry]}, handle)

    handler = HandleSiteVisitRoute()
    handler.run({"db": env["db"], "task_id": env["site_task_id"], "calendar_dir": env["calendar_dir"]})

    entry = _history_tail(env["db"], env["client_email"])
    assert entry["note"] == "visit: alternatives"
    lower = entry["message"].lower()
    assert "closest available alternatives" in lower or "fresh options" in lower


def test_site_visit_without_proposals_suggests_times(tmp_path: Path) -> None:
    env = _setup_site_visit_task(tmp_path, "Could we arrange a visit?")
    handler = HandleSiteVisitRoute()
    handler.run({"db": env["db"], "task_id": env["site_task_id"], "calendar_dir": env["calendar_dir"]})

    entry = _history_tail(env["db"], env["client_email"])
    assert entry["note"] == "visit: propose"
    assert "visit times" in entry["message"].lower()


def test_site_visit_hil_approval_confirms_visit(tmp_path: Path) -> None:
    env = _setup_site_visit_task(tmp_path, "Let's do 2030-04-10 15:00 for the visit.")
    handler = HandleSiteVisitRoute()
    handler.run({"db": env["db"], "task_id": env["site_task_id"], "calendar_dir": env["calendar_dir"]})

    hil_task = next(task for task in env["db"]["tasks"] if task["type"] == TaskType.SITE_VISIT_HIL_REVIEW.value)
    hil_task["status"] = TaskStatus.APPROVED.value

    client = env["db"]["clients"][env["client_email"]]
    client["history"].append(
        {
            "msg_id": "msg-ack",
            "ts": "2025-01-02T09:00:00Z",
            "subject": "Ack",
            "body_preview": "Thanks",
            "intent": "client_reply",
            "confidence": 0.5,
            "user_info": {},
            "post_offer_classification": _empty_site_visit_classification(),
        }
    )
    followup_task_id = enqueue_site_visit_followup(
        env["db"], env["client_email"], env["event_id"], "msg-ack"
    )

    handler.run({"db": env["db"], "task_id": followup_task_id, "calendar_dir": env["calendar_dir"]})

    notes = [entry.get("note") for entry in env["db"]["clients"][env["client_email"]]["history"] if "note" in entry]
    assert "visit: confirmed" in notes
    calendar_file = env["calendar_dir"] / "atelier-room-a.json"
    with calendar_file.open("r", encoding="utf-8") as handle:
        calendar_payload = json.load(handle)
    assert calendar_payload["busy"][0]["status"] == "confirmed"
    assert hil_task["status"] == TaskStatus.DONE.value
    assert hil_task["notes"] == "processed"


def test_site_visit_post_followup_after_visit(tmp_path: Path) -> None:
    env = _setup_site_visit_task(tmp_path, "Thanks for arranging the visit")
    calendar_file = env["calendar_dir"] / "atelier-room-a.json"
    past_start = "2023-01-05T10:00:00+01:00"
    past_end = "2023-01-05T11:00:00+01:00"
    hold_entry = {
        "start": past_start,
        "end": past_end,
        "description": "Viewing visit",
        "status": "confirmed",
        "category": "site_visit",
        "event_id": env["event_id"],
        "client_id": env["client_email"],
        "hold_id": f"{env['event_id']}:{past_start}",
        "room_name": "Room A",
    }
    with calendar_file.open("w", encoding="utf-8") as handle:
        json.dump({"busy": [hold_entry]}, handle)

    client = env["db"]["clients"][env["client_email"]]
    client["history"].append(
        {
            "msg_id": "msg-follow",
            "ts": "2025-01-06T09:00:00Z",
            "subject": "Follow",
            "body_preview": "Hello",
            "intent": "client_reply",
            "confidence": 0.5,
            "user_info": {},
            "post_offer_classification": _empty_site_visit_classification(),
        }
    )
    follow_task = enqueue_site_visit_followup(env["db"], env["client_email"], env["event_id"], "msg-follow")

    handler = HandleSiteVisitRoute()
    handler.run({"db": env["db"], "task_id": follow_task, "calendar_dir": env["calendar_dir"]})

    history_notes = [item.get("note") for item in env["db"]["clients"][env["client_email"]]["history"] if "note" in item]
    assert "visit: post-visit-followup" in history_notes

    # Second run should not duplicate the follow-up
    next_task = enqueue_site_visit_followup(env["db"], env["client_email"], env["event_id"], "msg-follow")
    handler.run({"db": env["db"], "task_id": next_task, "calendar_dir": env["calendar_dir"]})
    followup_notes = [item["note"] for item in env["db"]["clients"][env["client_email"]]["history"] if item.get("note") == "visit: post-visit-followup"]
    assert len(followup_notes) == 1
