import os
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.workflows.groups.offer.llm.client_reply_analysis import AnalyzeClientReply
from backend.workflows.groups.event_confirmation.condition.route_by_response_type import route_by_response_type
from backend.workflows.io.database import get_default_db

pytestmark = pytest.mark.skipif(
    os.getenv("OE_SKIP_TESTS", "1") == "1",
    reason="Skipping in constrained env; set OE_SKIP_TESTS=0 to run.",
)


def _make_history_entry(msg_id: str, **overrides: Dict[str, object]) -> Dict[str, object]:
    entry: Dict[str, object] = {
        "msg_id": msg_id,
        "ts": "2025-01-01T10:00:00Z",
        "subject": "Re: Offer",
        "body_preview": "Preview text",
        "intent": "event_request",
        "confidence": 1.0,
        "user_info": {},
    }
    entry.update(overrides)
    return entry


def _bootstrap_db(client_email: str, message_id: str) -> dict:
    return _bootstrap_db_many(client_email, [_make_history_entry(message_id)])


def _bootstrap_db_many(
    client_email: str,
    history_entries: Iterable[Dict[str, object]],
    event_ids: Optional[Iterable[str]] = ("EVT-1",),
) -> dict:
    db = get_default_db()
    db["clients"][client_email] = {
        "profile": {"name": None, "org": None, "phone": None},
        "history": list(history_entries),
        "event_ids": list(event_ids or []),
    }
    db["tasks"] = []
    return db


def test_analyze_confirm_booking_classification() -> None:
    node = AnalyzeClientReply()
    result = node.run({"client_msg_text": "We confirm the booking and the deposit is paid."})
    classification = result["post_offer_classification"]

    assert classification["response_type"] == "confirm_booking"
    assert 0.0 <= classification["classification_confidence"] <= 1.0
    fields = classification["extracted_fields"]
    assert fields["mentions_deposit"] is True
    assert fields["wants_to_pay_deposit_now"] is True
    assert fields["requested_reserve_dates"] == []
    assert fields["proposed_visit_datetimes"] == []


def test_analyze_site_visit_extracts_datetimes() -> None:
    node = AnalyzeClientReply()
    message = "Could we arrange a tour on 2025-04-10 15:30 or 2025-04-11 10:00?"
    result = node.run({"client_msg_text": message})
    classification = result["post_offer_classification"]

    assert classification["response_type"] == "site_visit"
    datetimes = classification["extracted_fields"]["proposed_visit_datetimes"]
    assert "2025-04-10T15:30" in datetimes
    assert "2025-04-11T10:00" in datetimes


def test_route_by_response_type_attaches_and_enqueues() -> None:
    client_email = "client@example.com"
    message_id = "msg-1"
    db = _bootstrap_db(client_email, message_id)

    node = AnalyzeClientReply()
    result = node.run({"client_msg_text": "Please reserve 2025-05-05 for us."})
    classification = result["post_offer_classification"]
    summary = route_by_response_type(
        db,
        client_email=client_email,
        message_id=message_id,
        classification=classification,
        event_id="EVT-1",
    )

    assert summary["routing_hint"] == "reserve_date"
    assert summary["message_msg_id"] == message_id

    history_entry = db["clients"][client_email]["history"][0]
    assert history_entry["post_offer_classification"]["response_type"] == "reserve_date"

    assert len(db["tasks"]) == 1
    task = db["tasks"][0]
    assert task["type"] == "route_post_offer"
    assert task["status"] == "pending"
    assert task["payload"] == {"routing_hint": "reserve_date", "message_msg_id": message_id}

    second = route_by_response_type(
        db,
        client_email=client_email,
        message_id=message_id,
        classification=classification,
        event_id="EVT-1",
    )
    assert second["task_id"] == summary["task_id"]
    assert len(db["tasks"]) == 1


def test_route_not_interested_maps_to_negotiate_or_close() -> None:
    client_email = "client@example.com"
    message_id = "msg-2"
    db = _bootstrap_db(client_email, message_id)

    node = AnalyzeClientReply()
    result = node.run({"client_msg_text": "Thanks, but we need to cancel and will go with another venue."})
    classification = result["post_offer_classification"]
    summary = route_by_response_type(
        db,
        client_email=client_email,
        message_id=message_id,
        classification=classification,
        event_id=None,
    )

    assert classification["response_type"] == "not_interested"
    assert summary["routing_hint"] == "negotiate_or_close"


def test_change_request_extracts_patch() -> None:
    node = AnalyzeClientReply()
    message = (
        "Could you change the event to 21.12.2025 starting at 18:00, ending at 22:00, "
        "and increase to 60 guests?"
    )
    result = node.run({"client_msg_text": message})
    classification = result["post_offer_classification"]

    assert classification["response_type"] == "change_request"
    fields = classification["extracted_fields"]
    patch = fields["change_request_patch"]
    assert patch.get("new_event_date") == "2025-12-21"
    assert patch.get("new_start_time") == "18:00"
    assert patch.get("new_end_time") == "22:00"
    assert patch.get("new_guest_count") == 60
    assert fields["requested_reserve_dates"] == []
    assert fields["proposed_visit_datetimes"] == []


def test_general_question_sets_text() -> None:
    node = AnalyzeClientReply()
    question = "Is the projector 4K and what's the ceiling height?"
    classification = node.run({"client_msg_text": question})["post_offer_classification"]

    assert classification["response_type"] == "general_question"
    fields = classification["extracted_fields"]
    assert fields["user_question_text"] == question
    assert fields["requested_reserve_dates"] == []
    assert fields["proposed_visit_datetimes"] == []
    assert fields["change_request_patch"] == {}


def test_site_visit_when_not_offered_notes_in_explanation() -> None:
    node = AnalyzeClientReply()
    payload = {
        "client_msg_text": "We'd love a tour on 2025-04-10 15:00 or 2025-04-11 11:15.",
        "visit_allowed": False,
    }
    classification = node.run(payload)["post_offer_classification"]

    assert classification["response_type"] == "site_visit"
    explanation = classification["classification_explanation"].lower()
    assert "visit_allowed is false" in explanation or "visits aren’t offered" in explanation
    datetimes = classification["extracted_fields"]["proposed_visit_datetimes"]
    assert "2025-04-10T15:00" in datetimes
    assert "2025-04-11T11:15" in datetimes


def test_reserve_eu_date_parsing() -> None:
    node = AnalyzeClientReply()
    classification = node.run({"client_msg_text": "Please hold 07.03.2026 for us."})["post_offer_classification"]

    assert classification["response_type"] == "reserve_date"
    fields = classification["extracted_fields"]
    assert fields["requested_reserve_dates"] == ["2026-03-07"]
    assert fields["proposed_visit_datetimes"] == []
    assert fields["change_request_patch"] == {}


def test_single_label_and_empty_fields_discipline() -> None:
    node = AnalyzeClientReply()
    classification = node.run({"client_msg_text": "Great, we confirm the booking."})["post_offer_classification"]

    assert classification["response_type"] == "confirm_booking"
    fields = classification["extracted_fields"]
    assert fields["proposed_visit_datetimes"] == []
    assert fields["requested_reserve_dates"] == []
    assert fields["change_request_patch"] == {}


def test_idempotency_overwrite_and_no_duplicate_task() -> None:
    client_email = "client@example.com"
    message_id = "msg-idem"
    db = _bootstrap_db(client_email, message_id)
    node = AnalyzeClientReply()

    first = node.run({"client_msg_text": "Please reserve 07.03.2026 for us."})["post_offer_classification"]
    summary_first = route_by_response_type(
        db,
        client_email=client_email,
        message_id=message_id,
        classification=first,
        event_id="EVT-1",
    )
    history_entry = db["clients"][client_email]["history"][0]
    first_expl = history_entry["post_offer_classification"]["classification_explanation"]
    assert summary_first["routing_hint"] == "reserve_date"
    assert len(db["tasks"]) == 1
    first_task_id = db["tasks"][0]["task_id"]

    second = node.run({"client_msg_text": "We confirm and the deposit is paid."})["post_offer_classification"]
    summary_second = route_by_response_type(
        db,
        client_email=client_email,
        message_id=message_id,
        classification=second,
        event_id="EVT-1",
    )
    history_entry = db["clients"][client_email]["history"][0]
    second_expl = history_entry["post_offer_classification"]["classification_explanation"]
    assert second_expl != first_expl
    assert history_entry["post_offer_classification"]["response_type"] == "confirm_booking"
    assert len(db["tasks"]) == 1
    assert db["tasks"][0]["task_id"] == first_task_id == summary_second["task_id"]
    assert db["tasks"][0]["payload"]["routing_hint"] == "confirm_booking"


def test_targets_correct_history_entry_when_multiple() -> None:
    client_email = "client@example.com"
    history = [
        _make_history_entry("msg-a"),
        _make_history_entry("msg-b"),
    ]
    db = _bootstrap_db_many(client_email, history)

    node = AnalyzeClientReply()
    classification = node.run({"client_msg_text": "Please reserve 2025-05-01."})["post_offer_classification"]
    route_by_response_type(
        db,
        client_email=client_email,
        message_id="msg-b",
        classification=classification,
        event_id="EVT-1",
    )

    first_entry = db["clients"][client_email]["history"][0]
    second_entry = db["clients"][client_email]["history"][1]
    assert "post_offer_classification" not in first_entry
    assert second_entry["post_offer_classification"]["response_type"] == "reserve_date"
    assert len(db["tasks"]) == 1
    assert db["tasks"][0]["payload"]["message_msg_id"] == "msg-b"


def test_explanation_and_confidence_present() -> None:
    node = AnalyzeClientReply()
    classification = node.run({"client_msg_text": "We confirm and look forward to it."})["post_offer_classification"]

    assert 0.0 <= classification["classification_confidence"] <= 1.0
    assert isinstance(classification["classification_explanation"], str)
    assert classification["classification_explanation"]


def test_precedence_change_over_reserve_when_both_present() -> None:
    node = AnalyzeClientReply()
    message = "Could you move us to 21.12.2025 and hold it for the team?"
    classification = node.run({"client_msg_text": message})["post_offer_classification"]

    assert classification["response_type"] == "change_request"
    patch = classification["extracted_fields"]["change_request_patch"]
    assert patch.get("new_event_date") == "2025-12-21"
    assert classification["extracted_fields"]["requested_reserve_dates"] == []
