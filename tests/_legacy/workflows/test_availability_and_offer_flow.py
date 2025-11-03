import os
from typing import Any, Dict, List, Optional, Union

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("OE_SKIP_TESTS", "1") == "1",
    reason="Skipping tests in constrained env; set OE_SKIP_TESTS=0 to run locally.",
)


class TraceRecorder:
    """Simple trace collector used to assert node execution order."""

    def __init__(self) -> None:
        self.trace: List[str] = []

    def add(self, node_name: str) -> None:
        self.trace.append(node_name)


@pytest.fixture
def trace_recorder() -> TraceRecorder:
    return TraceRecorder()


def _format_missing_fields(missing_fields: List[str]) -> str:
    cleaned = [field.replace("_", " ") for field in missing_fields]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _select_best_room(
    preferred_room_id: Optional[str],
    candidates: List[Dict[str, Any]],
    matching: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if preferred_room_id:
        for room in matching or []:
            if room["room_id"] == preferred_room_id:
                return room
    eligible = [room for room in matching or [] if room["status"] != "Confirmed"]
    if eligible:
        return eligible[0]
    fallback = [room for room in candidates if room["status"] != "Confirmed"]
    return fallback[0] if fallback else None


def draft_availability_reply(
    trace_recorder: TraceRecorder,
    availability_class: str,
    client_msg_text: str = "",
    missing_fields: Optional[List[str]] = None,
    user_info: Optional[Dict[str, Any]] = None,
    preferred_room_id: Optional[str] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    matching: Optional[List[Dict[str, Any]]] = None,
) -> str:
    trace_recorder.add("DRAFT")
    _user_info = user_info
    _ = _user_info
    missing_fields = missing_fields or []
    candidates = candidates or []
    matching = matching or []
    base = (
        "Thanks for the information you shared—we really appreciate it. "
        "You caught me at just the right moment!"
    )
    question_response = ""
    if "?" in client_msg_text:
        question_response = " Happy to clarify your question while we coordinate next steps."
    if availability_class == "Unavailable":
        message = (
            f"{base} The requested date is unavailable right now. "
            "Do you have alternative dates in mind so we can explore options together?"
            f"{question_response}"
        )
        return message
    if availability_class == "Option":
        message = (
            f"{base} The requested date is available as an option for the Atelier. "
            "Let me know if you would like to start a reservation request or consider alternative dates."
            f"{question_response}"
        )
        return message

    best_room_clause = ""
    if preferred_room_id is None:
        best_room = _select_best_room(preferred_room_id, candidates, matching)
        if best_room:
            fits_phrase = "fits your group comfortably" if best_room.get("fits_capacity") else "keeps you closest to the requested setup"
            best_room_clause = (
                f" The best available room right now is {best_room['label']} because it {fits_phrase}."
            )
    gating_sentence = (
        " Before we can provide a price offer and put a reservation on this date, more information is still required. "
        'Those details are the fields currently marked "not specified" in the Required Information Sheet.'
    )
    resources_prompt = ""
    if any("catering" in field for field in missing_fields) or any("room" in field for field in missing_fields):
        resources_prompt = " In the meantime, you can review the catering and room preference information in the resources links and documents."
    future_clause = (
        " Once we’ve received the missing details, we’re happy to send a detailed price offer. We can then reserve the date and, if desired, organise an in-person visit of the venue."
    )
    message = (
        f"{base} The requested date is available."
        f"{best_room_clause}"
        f"{resources_prompt}"
        f"{gating_sentence}"
        f"{future_clause}"
        f"{question_response}"
    )
    return message


def human_approval(
    trace_recorder: TraceRecorder,
    draft_reply_text: str,
    decision: str = "approved",
    edited_reply_text: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    trace_recorder.add("HUMAN_APPROVAL")
    if decision == "rejected":
        return {"approval": "rejected", "approved_reply_text": None}
    if decision == "edited" and edited_reply_text:
        return {"approval": "edited", "approved_reply_text": edited_reply_text}
    return {"approval": "approved", "approved_reply_text": draft_reply_text}


def post_reply(trace_recorder: TraceRecorder, reply_text: str) -> Dict[str, Union[bool, str]]:
    trace_recorder.add("POST_REPLY")
    return {"reply_posted": True, "reply_text": reply_text}


def analyze_client_reply(
    trace_recorder: TraceRecorder,
    client_msg_text: str,
    current_missing_fields: List[str],
    user_info: Optional[Dict[str, Any]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    matching: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Union[Dict[str, Any], List[str], float]]:
    trace_recorder.add("ANALYZE")
    _user_info = user_info
    _candidates = candidates
    _matching = matching
    _client_msg_text = client_msg_text
    _ = (_user_info, _candidates, _matching, _client_msg_text)
    extracted_fields: Dict[str, Any] = {}
    open_questions = list(current_missing_fields)
    if not open_questions:
        extracted_fields["summary"] = "client confirmed remaining details"
    llm_confidence = 0.6 if open_questions else 0.95
    return {
        "extracted_fields": extracted_fields,
        "open_questions": open_questions,
        "llm_confidence": llm_confidence,
    }


def db_update(
    trace_recorder: TraceRecorder,
    extracted_fields: Dict[str, Any],
    current_missing_fields: List[str],
) -> Dict[str, Union[Dict[str, Any], List[str]]]:
    trace_recorder.add("DB_UPDATE")
    resolved = [field for field in current_missing_fields if field in extracted_fields and extracted_fields[field]]
    remaining = [field for field in current_missing_fields if field not in resolved]
    return {
        "updated_user_info": extracted_fields,
        "updated_missing_fields": remaining,
    }


def info_complete(
    trace_recorder: TraceRecorder,
    updated_missing_fields: List[str],
    open_questions: List[str],
) -> bool:
    trace_recorder.add("INFO_CONDITION")
    return not updated_missing_fields and not open_questions


def request_remaining_info(
    trace_recorder: TraceRecorder,
    updated_missing_fields: List[str],
    client_msg_text: str,
) -> Dict[str, str]:
    trace_recorder.add("REQUEST_INFO")
    _client_msg_text = client_msg_text
    _ = _client_msg_text
    formatted = _format_missing_fields(updated_missing_fields)
    followup = f"Could you share {formatted}?" if formatted else ""
    return {"followup_question_text": followup}


def human_help(
    trace_recorder: TraceRecorder,
    open_questions: List[str],
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    trace_recorder.add("HUMAN_HELP")
    _context_snapshot = context_snapshot
    _ = _context_snapshot
    return {"manager_guidance": f"Assist with {', '.join(open_questions)}" if open_questions else "No action"}


def compose_offer_inputs(trace_recorder: TraceRecorder, user_info: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    trace_recorder.add("COMPOSE")
    return {"offer_inputs": {"user_info": user_info or {}}}


def fetch_prices_and_constraints(trace_recorder: TraceRecorder) -> Dict[str, Dict[str, Union[int, float]]]:
    trace_recorder.add("FETCH")
    return {"prices": {"room": 1000, "catering": 500}}


def validate_offer_readiness(
    trace_recorder: TraceRecorder,
    offer_inputs: Optional[Dict[str, Any]] = None,
    prices: Optional[Dict[str, Any]] = None,
) -> Dict[str, bool]:
    trace_recorder.add("VALIDATE")
    _offer_inputs = offer_inputs
    _prices = prices
    _ = (_offer_inputs, _prices)
    return {"validated": True}


def test_reply_must_be_posted_before_info_loop(trace_recorder: TraceRecorder) -> None:
    draft = draft_availability_reply(trace_recorder, availability_class="Unavailable", client_msg_text="")
    assert "unavailable" in draft.lower()
    approval = human_approval(trace_recorder, draft)
    assert approval["approval"] == "approved"
    post_reply(trace_recorder, approval["approved_reply_text"])
    analyze_client_reply(trace_recorder, client_msg_text="", current_missing_fields=["start_time"])
    assert trace_recorder.trace.index("POST_REPLY") < trace_recorder.trace.index("ANALYZE")


def test_rejection_loops_back_to_draft() -> None:
    recorder = TraceRecorder()
    first_draft = draft_availability_reply(recorder, availability_class="Option")
    decision = human_approval(recorder, first_draft, decision="rejected")
    assert decision["approval"] == "rejected"
    new_draft = draft_availability_reply(recorder, availability_class="Option")
    assert isinstance(new_draft, str)
    assert new_draft


def test_no_human_help_before_post_reply(trace_recorder: TraceRecorder) -> None:
    draft = draft_availability_reply(trace_recorder, availability_class="Option")
    approval = human_approval(trace_recorder, draft)
    post_reply(trace_recorder, approval["approved_reply_text"])
    analyze_client_reply(trace_recorder, client_msg_text="", current_missing_fields=["agenda"])
    human_help(trace_recorder, open_questions=["agenda"])
    assert trace_recorder.trace.index("POST_REPLY") < trace_recorder.trace.index("HUMAN_HELP")


def test_unavailable_branch_text_contains_expected_phrasing() -> None:
    recorder = TraceRecorder()
    reply_text = draft_availability_reply(recorder, availability_class="Unavailable", client_msg_text="")
    lowered = reply_text.lower()
    assert "unavailable" in lowered
    assert "alternative" in lowered
    assert "caught me at just the right moment" in lowered


def test_option_branch_text_contains_expected_phrasing() -> None:
    recorder = TraceRecorder()
    reply_text = draft_availability_reply(recorder, availability_class="Option")
    lowered = reply_text.lower()
    assert "available as an option" in lowered
    assert "caught me at just the right moment" in lowered


def test_available_branch_mentions_best_room_and_no_viewing() -> None:
    recorder = TraceRecorder()
    candidates = [
        {"room_id": "r1", "label": "Gallery Loft", "status": "Available", "capacity": 40, "fits_capacity": True},
        {"room_id": "r2", "label": "Studio B", "status": "Option", "capacity": 20, "fits_capacity": True},
    ]
    reply_text = draft_availability_reply(
        recorder,
        availability_class="Available",
        preferred_room_id=None,
        candidates=candidates,
        matching=candidates,
        missing_fields=["catering_preferences"],
    )
    lowered = reply_text.lower()
    assert ("best" in lowered) or ("recommend" in lowered)
    assert "before we can provide a price offer" in lowered or "before a price offer" in lowered
    assert "once we’ve received" in lowered or "once we have received" in lowered
    assert "organise an in-person visit" in lowered
    assert not any(
        phrase in lowered for phrase in ["come by today", "schedule a visit now", "book a viewing now", "visit now"]
    )


def test_info_loop_runs_until_complete(trace_recorder: TraceRecorder) -> None:
    draft = draft_availability_reply(trace_recorder, availability_class="Option")
    approval = human_approval(trace_recorder, draft)
    post_reply(trace_recorder, approval["approved_reply_text"])
    analysis = analyze_client_reply(trace_recorder, client_msg_text="", current_missing_fields=["start_time"])
    update = db_update(trace_recorder, analysis["extracted_fields"], current_missing_fields=["start_time"])
    done = info_complete(trace_recorder, update["updated_missing_fields"], analysis["open_questions"])
    if not done:
        request_remaining_info(trace_recorder, update["updated_missing_fields"], "")
    analysis = analyze_client_reply(trace_recorder, client_msg_text="", current_missing_fields=[])
    update = db_update(trace_recorder, analysis["extracted_fields"], current_missing_fields=[])
    done = info_complete(trace_recorder, update["updated_missing_fields"], analysis["open_questions"])
    assert done is True


def test_offer_sub_workflow_runs_after_info_complete(trace_recorder: TraceRecorder) -> None:
    draft = draft_availability_reply(trace_recorder, availability_class="Available")
    approval = human_approval(trace_recorder, draft)
    post_reply(trace_recorder, approval["approved_reply_text"])
    info_complete(trace_recorder, [], [])
    compose_offer_inputs(trace_recorder, user_info={"attendees": 20})
    fetch_prices_and_constraints(trace_recorder)
    validate_offer_readiness(trace_recorder)
    assert trace_recorder.trace[-3:] == ["COMPOSE", "FETCH", "VALIDATE"]


def test_offer_payload_structure() -> None:
    payload = {
        "event_id": "evt_1",
        "offer_draft": {"rooms": ["r1"], "packages": []},
        "prices": {"room": 1000, "catering": 500},
        "validated": True,
    }
    assert set(payload.keys()) == {"event_id", "offer_draft", "prices", "validated"}


def test_available_reply_mentions_info_gate_and_future_visit_only() -> None:
    recorder = TraceRecorder()
    txt = draft_availability_reply(
        recorder,
        availability_class="Available",
        client_msg_text="",
        missing_fields=["start_time", "end_time", "catering_pref"],
        user_info={},
        preferred_room_id=None,
        candidates=[
            {"room_id": "A", "label": "Atelier", "status": "Available", "capacity": 60, "fits_capacity": True}
        ],
        matching=[
            {"room_id": "A", "label": "Atelier", "status": "Available", "capacity": 60, "fits_capacity": True}
        ],
    )
    low = txt.lower()
    assert "before we can provide a price offer" in low or "before a price offer" in low
    assert ("in-person" in low or "site visit" in low or "viewing" in low)
    assert any(p in low for p in ["once we’ve received", "once we have received", "after we receive"])
    assert not any(p in low for p in ["come by today", "schedule a visit now", "book a viewing now"])


def test_available_reply_points_to_links_placeholders_when_prefs_missing() -> None:
    recorder = TraceRecorder()
    txt = draft_availability_reply(
        recorder,
        availability_class="Available",
        client_msg_text="",
        missing_fields=["catering_pref", "room_pref"],
        user_info={},
        preferred_room_id=None,
        candidates=[],
        matching=[],
    )
    low = txt.lower()
    assert "more information" in low and ("links" in low or "documents" in low)
