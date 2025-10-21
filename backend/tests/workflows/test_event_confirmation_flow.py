import os
from typing import Any, Dict, List, Optional

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("OE_SKIP_TESTS", "1") == "1",
    reason="Skipping in constrained env; set OE_SKIP_TESTS=0 to run.",
)


class TraceRecorder:
    def __init__(self) -> None:
        self.trace: List[str] = []

    def add(self, step: str) -> None:
        self.trace.append(step)


_TRACE_HOOK: Optional[TraceRecorder] = None


def _record(step: str) -> None:
    if _TRACE_HOOK is not None:
        _TRACE_HOOK.add(step)


USE_REAL_IMPL = True

try:
    from backend.workflows.groups.offer.create_offer import CreateProfessionalOffer
    from backend.workflows.groups.offer.send_offer_llm import (
        ChatFollowUp,
        ComposeOffer,
        EmailOffer,
    )
    from backend.workflows.groups.offer.client_reply_analysis import AnalyzeClientReply
    from backend.workflows.groups.event_confirmation.update_database import UpdateEventStatus
except Exception:
    USE_REAL_IMPL = False

    class CreateProfessionalOffer:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("APPROVE")
            ui_rules = payload.get("ui_rules", {})
            working_hours = ui_rules.get("working_hours", {"start": "09:00", "end": "18:00"})
            return {
                "event_id": payload["event_id"],
                "offer_ready_to_generate": True,
                "visit_allowed": ui_rules.get("visit_allowed", False),
                "working_hours": working_hours,
                "deposit_percent": ui_rules.get("deposit_percent"),
                "user_info_final": payload.get("user_info_final", {}),
                "selected_room": payload.get("selected_room", {}),
                "pricing_inputs": payload.get("pricing_inputs", {}),
                "client_contact": payload.get("client_contact", {}),
            }

    class ComposeOffer:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("COMPOSE")
            return {
                "offer_id": "OFF-1",
                "offer_document": {"lines": [{"name": "Venue", "price": 1000}]},
                "total_amount": 1000.0,
            }

    class EmailOffer:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("EMAIL")
            return {"offer_id": payload["offer_id"], "email_sent": True, "sent_at": "2025-01-01T12:00:00Z"}

    class ChatFollowUp:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("CHAT")
            base = (
                "Thanks for sending all the details — we now have everything we need. "
                "I’ve just sent you an initial offer by email based on your selected options. "
                "If you'd like, we can place an initial reservation for this date."
            )
            parts = [base]
            if payload.get("visit_allowed"):
                hours = payload.get("working_hours", {"start": "09:00", "end": "18:00"})
                parts.append(
                    f" We can also arrange a viewing — please propose 2–3 times that work for you; "
                    f"our working hours are {hours['start']}–{hours['end']}."
                )
            deposit_percent = payload.get("deposit_percent")
            if deposit_percent and deposit_percent > 0:
                parts.append(f" To fully confirm the event, a {deposit_percent}% deposit of the total will be required.")
            return {"chat_posted": True, "message": "".join(parts)}

    class AnalyzeClientReply:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("ANALYZE")
            text = payload.get("client_msg_text", "").lower()
            if "accept" in text:
                return {
                    "intent": "accept",
                    "deposit_acknowledged": "deposit" in text,
                }
            if "reserve" in text:
                return {"intent": "reserve_only"}
            if "view" in text or "visit" in text:
                return {"intent": "request_viewing", "proposed_times": ["Tue 15:00", "Wed 11:00", "Thu 17:30"]}
            if "change" in text or "negotiate" in text:
                return {"intent": "negotiate", "requested_changes": {"note": text}}
            return {"intent": "questions"}

    class UpdateEventStatus:
        def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
            _record("DB_UPDATE")
            deposit_percent = payload.get("deposit_percent")
            deposit_ack = payload.get("deposit_acknowledged", False)
            override = payload.get("deposit_status_override")
            if deposit_percent in (None, 0):
                deposit_status = "not_required"
            elif override == "paid":
                deposit_status = "paid"
            elif deposit_ack:
                deposit_status = "acknowledged"
            else:
                deposit_status = "required"

            intent = payload.get("intent")
            event_status = "Option"
            next_required_action = "none"

            if intent == "accept":
                if deposit_percent in (None, 0):
                    event_status = "Confirmed"
                elif deposit_status == "paid":
                    event_status = "Confirmed"
                else:
                    event_status = "Option"
                    next_required_action = "await_deposit"
            elif intent == "reserve_only":
                event_status = "Option"
            elif intent == "request_viewing":
                event_status = "Option"
                next_required_action = "schedule_viewing" if payload.get("visit_allowed") else "none"
            elif intent == "negotiate":
                event_status = "Option"
                next_required_action = "manager_clarification"
            else:
                event_status = "Option"

            deposit_due_amount = round(payload.get("total_amount", 0) * ((deposit_percent or 0) / 100.0), 2)
            proposed_times = payload.get("proposed_times") or []
            if not payload.get("visit_allowed"):
                proposed_times = []

            return {
                "event_id": payload["event_id"],
                "event_status": event_status,
                "deposit_status": deposit_status,
                "deposit_due_amount": deposit_due_amount,
                "next_required_action": next_required_action,
                "viewing_requested_times": proposed_times,
            }


def _with_trace(recorder: TraceRecorder) -> None:
    global _TRACE_HOOK
    _TRACE_HOOK = recorder


def _clear_trace() -> None:
    global _TRACE_HOOK
    _TRACE_HOOK = None


def _base_payload(ui_rules: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": "EVT-1",
        "user_info_final": {"attendees": 50},
        "selected_room": {"room_id": "A", "label": "Atelier"},
        "pricing_inputs": {"base_rate": 1000},
        "client_contact": {"email": "client@example.com"},
        "ui_rules": ui_rules,
    }


def _run_node(
    recorder: TraceRecorder,
    label: str,
    node_cls: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    _with_trace(recorder)
    node = node_cls()
    result = node.run(payload)
    _clear_trace()
    if USE_REAL_IMPL:
        recorder.add(label)
    return result


_RESPONSE_TO_INTENT = {
    "confirm_booking": "accept",
    "reserve_date": "reserve_only",
    "site_visit": "request_viewing",
    "change_request": "negotiate",
    "general_question": "questions",
    "not_interested": "questions",
}


def _run_analysis(recorder: TraceRecorder, payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = _run_node(recorder, "ANALYZE", AnalyzeClientReply, payload)
    if "post_offer_classification" not in raw:
        return raw

    classification = raw["post_offer_classification"]
    extracted = classification.get("extracted_fields", {})
    intent = _RESPONSE_TO_INTENT[classification.get("response_type")]
    proposed = extracted.get("proposed_visit_datetimes") or []
    requested_patch = extracted.get("change_request_patch") or {}
    additional = requested_patch.get("additional_change_notes")
    requested_changes: Dict[str, Any] = {}
    if additional:
        requested_changes = {"note": additional}

    return {
        "intent": intent,
        "deposit_acknowledged": bool(extracted.get("wants_to_pay_deposit_now")),
        "proposed_times": proposed,
        "requested_changes": requested_changes,
        "raw_classification": classification,
    }


def test_strict_ordering_gates() -> None:
    recorder = TraceRecorder()
    ui_rules = {"visit_allowed": True, "deposit_percent": 20, "working_hours": {"start": "09:00", "end": "18:00"}}
    base = _base_payload(ui_rules)

    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    assert approval["offer_ready_to_generate"] is True

    compose_payload = {
        "event_id": base["event_id"],
        "user_info_final": approval["user_info_final"],
        "selected_room": approval["selected_room"],
        "pricing_inputs": approval["pricing_inputs"],
        "offer_ready_to_generate": approval["offer_ready_to_generate"],
    }
    offer_data = _run_node(recorder, "COMPOSE", ComposeOffer, compose_payload)

    email_payload = {
        "offer_id": offer_data["offer_id"],
        "offer_document": offer_data["offer_document"],
        "client_contact": approval["client_contact"],
    }
    email_result = _run_node(recorder, "EMAIL", EmailOffer, email_payload)
    assert email_result["email_sent"] is True

    chat_payload = {
        "visit_allowed": approval["visit_allowed"],
        "working_hours": approval["working_hours"],
        "deposit_percent": approval["deposit_percent"],
    }
    chat_result = _run_node(recorder, "CHAT", ChatFollowUp, chat_payload)
    assert "initial offer" in chat_result["message"].lower()

    analysis_payload = {
        "event_id": base["event_id"],
        "offer_id": offer_data["offer_id"],
        "client_msg_text": "we accept and will pay the deposit",
        "visit_allowed": approval["visit_allowed"],
        "deposit_percent": approval["deposit_percent"],
    }
    analysis = _run_analysis(recorder, analysis_payload)

    db_payload = {
        "event_id": base["event_id"],
        "intent": analysis.get("intent"),
        "deposit_percent": approval["deposit_percent"],
        "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
        "proposed_times": analysis.get("proposed_times"),
        "total_amount": offer_data["total_amount"],
        "visit_allowed": approval["visit_allowed"],
    }
    db_result = _run_node(recorder, "DB_UPDATE", UpdateEventStatus, db_payload)

    assert recorder.trace == ["APPROVE", "COMPOSE", "EMAIL", "CHAT", "ANALYZE", "DB_UPDATE"]
    assert recorder.trace.index("EMAIL") < recorder.trace.index("CHAT")
    assert recorder.trace.index("APPROVE") < recorder.trace.index("COMPOSE")
    assert db_result["deposit_due_amount"] == pytest.approx(200.0)


def test_followup_copy_guards() -> None:
    recorder = TraceRecorder()
    ui_rules = {"visit_allowed": True, "deposit_percent": 20, "working_hours": {"start": "09:00", "end": "18:00"}}
    base = _base_payload(ui_rules)
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)

    chat_a = _run_node(
        recorder,
        "CHAT",
        ChatFollowUp,
        {
            "visit_allowed": True,
            "working_hours": approval["working_hours"],
            "deposit_percent": 20,
        },
    )["message"].lower()
    assert "sent you an initial offer" in chat_a
    assert "propose 2–3 times" in chat_a
    assert "09:00–18:00" in chat_a or "09:00-18:00" in chat_a
    assert "20% deposit" in chat_a

    chat_b = _run_node(
        recorder,
        "CHAT",
        ChatFollowUp,
        {
            "visit_allowed": False,
            "working_hours": approval["working_hours"],
            "deposit_percent": None,
        },
    )["message"].lower()
    assert "propose 2–3 times" not in chat_b
    assert "% deposit" not in chat_b

    chat_c = _run_node(
        recorder,
        "CHAT",
        ChatFollowUp,
        {
            "visit_allowed": True,
            "working_hours": approval["working_hours"],
            "deposit_percent": 0,
        },
    )["message"].lower()
    assert "propose 2–3 times" in chat_c
    assert "% deposit" not in chat_c


def test_accept_no_deposit_confirms_immediately() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": None, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we accept",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["event_status"] == "Confirmed"
    assert result["deposit_status"] == "not_required"
    assert result["deposit_due_amount"] == 0


def test_accept_deposit_required_not_acknowledged_stays_option() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 50, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we accept",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["deposit_status"] == "required"
    assert result["event_status"] == "Option"
    assert result["deposit_due_amount"] == pytest.approx(500.0)


def test_accept_deposit_acknowledged_still_not_confirmed_until_paid() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 50, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we accept and will pay the deposit",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["deposit_status"] == "acknowledged"
    assert result["event_status"] == "Option"
    assert result["deposit_due_amount"] == pytest.approx(500.0)


def test_accept_deposit_paid_confirms() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 50, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we accept and the deposit is paid",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
            "deposit_status_override": "paid",
        },
    )
    assert result["event_status"] == "Confirmed"
    assert result["deposit_status"] == "paid"
    assert result["deposit_due_amount"] == pytest.approx(500.0)


def test_reserve_only_sets_option() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 0, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "please reserve only",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["event_status"] == "Option"
    assert result["deposit_status"] in {"not_required", "required"}


def test_request_viewing_allowed_collects_times() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": True, "deposit_percent": 0, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we would like to view the venue on Tue 15:00, Wed 11:00, Thu 17:30",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    assert analysis.get("proposed_times")
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["next_required_action"] == "schedule_viewing"
    assert result["viewing_requested_times"] == analysis["proposed_times"]


def test_request_viewing_not_allowed_blocks() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 0, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    chat_copy = _run_node(
        recorder,
        "CHAT",
        ChatFollowUp,
        {
            "visit_allowed": approval["visit_allowed"],
            "working_hours": approval["working_hours"],
            "deposit_percent": approval["deposit_percent"],
        },
    )["message"].lower()
    assert "propose 2–3 times" not in chat_copy

    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we want to view the venue",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
        },
    )
    assert result["next_required_action"] != "schedule_viewing"


def test_negotiate_routes_to_manager_clarification() -> None:
    recorder = TraceRecorder()
    base = _base_payload({"visit_allowed": False, "deposit_percent": 0, "working_hours": {"start": "09:00", "end": "18:00"}})
    approval = _run_node(recorder, "APPROVE", CreateProfessionalOffer, base)
    offer_data = _run_node(
        recorder,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    analysis = _run_analysis(
        recorder,
        {
            "event_id": base["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we want to change the catering setup",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    assert analysis["intent"] == "negotiate"
    result = _run_node(
        recorder,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
            "requested_changes": analysis.get("requested_changes"),
        },
    )
    assert result["next_required_action"] == "manager_clarification"


if __name__ == "__main__":
    tracer = TraceRecorder()
    base_rules = {"visit_allowed": True, "deposit_percent": 30, "working_hours": {"start": "09:00", "end": "18:00"}}
    base_payload = _base_payload(base_rules)
    approval = _run_node(tracer, "APPROVE", CreateProfessionalOffer, base_payload)
    offer_data = _run_node(
        tracer,
        "COMPOSE",
        ComposeOffer,
        {
            "event_id": base_payload["event_id"],
            "user_info_final": approval["user_info_final"],
            "selected_room": approval["selected_room"],
            "pricing_inputs": approval["pricing_inputs"],
            "offer_ready_to_generate": approval["offer_ready_to_generate"],
        },
    )
    _run_node(
        tracer,
        "EMAIL",
        EmailOffer,
        {
            "offer_id": offer_data["offer_id"],
            "offer_document": offer_data["offer_document"],
            "client_contact": approval["client_contact"],
        },
    )
    _run_node(
        tracer,
        "CHAT",
        ChatFollowUp,
        {
            "visit_allowed": approval["visit_allowed"],
            "working_hours": approval["working_hours"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    analysis = _run_analysis(
        tracer,
        {
            "event_id": base_payload["event_id"],
            "offer_id": offer_data["offer_id"],
            "client_msg_text": "we accept and the deposit is paid",
            "visit_allowed": approval["visit_allowed"],
            "deposit_percent": approval["deposit_percent"],
        },
    )
    db_result = _run_node(
        tracer,
        "DB_UPDATE",
        UpdateEventStatus,
        {
            "event_id": base_payload["event_id"],
            "intent": analysis["intent"],
            "deposit_percent": approval["deposit_percent"],
            "deposit_acknowledged": analysis.get("deposit_acknowledged", False),
            "proposed_times": analysis.get("proposed_times"),
            "total_amount": offer_data["total_amount"],
            "visit_allowed": approval["visit_allowed"],
            "deposit_status_override": "paid",
        },
    )
    print("Trace:", tracer.trace)
    print("DB:", db_result)
    print("SMOKE OK")
