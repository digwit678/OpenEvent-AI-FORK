from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.domain import EventStatus, IntentLabel
from backend.workflows.common.billing import (
    billing_prompt_for_missing_fields,
    missing_billing_fields,
    update_billing_details,
)
from backend.workflows.common.capture import capture_user_fields, promote_billing_from_captured
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.room_rules import site_visit_allowed
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.utils.profiler import profile_step
from backend.workflows.common.gatekeeper import explain_step7_gate, refresh_gatekeeper

__workflow_role__ = "trigger"


CONFIRM_KEYWORDS = ("confirm", "go ahead", "locked", "booked", "ready to proceed", "accept")
RESERVE_KEYWORDS = ("reserve", "hold", "pencil", "option")
VISIT_KEYWORDS = ("visit", "tour", "view", "walkthrough", "see the space", "stop by")
DECLINE_KEYWORDS = ("cancel", "decline", "not interested", "no longer", "won't proceed")
CHANGE_KEYWORDS = ("change", "adjust", "different", "increase", "decrease", "move", "switch")
QUESTION_KEYWORDS = ("could", "would", "do you", "can you")


@profile_step("workflow.step7.confirmation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Step 7 — final confirmation handling with deposit/site-visit flows."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": None,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event",
            "context": state.context_snapshot,
        }
        return GroupResult(action="confirmation_missing_event", payload=payload, halt=True)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    state.current_step = 7
    state.telemetry.final_action = "none"
    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})

    if state.user_info.get("hil_approve_step") == 7:
        return _process_hil_confirmation(state, event_entry)

    capture_user_fields(state, current_step=7, source=state.message.msg_id)
    promote_billing_from_captured(state, event_entry)

    _sync_gate_context(state, event_entry)

    structural = _detect_structural_change(state.user_info, event_entry, state.intent)
    if structural:
        target_step, reason, details = structural
        return _launch_edit_detour(state, event_entry, target_step, reason, details)

    message_text = (state.message.body or "").strip()
    classification = _classify_message(message_text, event_entry)
    conf_state["last_response_type"] = classification

    if classification == "confirm":
        return _prepare_confirmation(state, event_entry)
    if classification == "deposit_paid":
        return _handle_deposit_paid(state, event_entry)
    if classification == "reserve":
        return _handle_reserve(state, event_entry)
    if classification == "site_visit":
        return _handle_site_visit(state, event_entry)
    if classification == "decline":
        return _handle_decline(state, event_entry)
    if classification == "change":
        # No structured change detected; fall back to clarification.
        return _handle_question(state)
    return _handle_question(state)


def _classify_message(message_text: str, event_entry: Dict[str, Any]) -> str:
    lowered = message_text.lower()

    deposit_state = event_entry.get("deposit_state") or {}
    if deposit_state.get("status") in {"requested", "awaiting_payment"}:
        if _contains_word(lowered, "deposit") and any(
            _contains_word(lowered, token) for token in ("paid", "sent", "transferred", "settled")
        ):
            return "deposit_paid"

    if _any_keyword_match(lowered, CONFIRM_KEYWORDS):
        return "confirm"
    if _any_keyword_match(lowered, VISIT_KEYWORDS):
        return "site_visit"
    if _any_keyword_match(lowered, RESERVE_KEYWORDS):
        return "reserve"
    if _any_keyword_match(lowered, DECLINE_KEYWORDS):
        return "decline"
    if _any_keyword_match(lowered, CHANGE_KEYWORDS):
        return "change"
    if "?" in lowered or any(token in lowered for token in QUESTION_KEYWORDS):
        return "question"
    return "question"


def _detect_structural_change(
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    intent: Optional[IntentLabel],
) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if new_iso_date or new_ddmmyyyy:
        candidate = new_ddmmyyyy or _iso_to_ddmmyyyy(new_iso_date)
        if candidate and candidate != event_entry.get("chosen_date"):
            details = {
                "type": IntentLabel.EDIT_DATE.value,
                "previous": event_entry.get("chosen_date"),
                "new": candidate,
            }
            return 2, "confirmation_changed_date", details

    new_room = user_info.get("room")
    if new_room and new_room != event_entry.get("locked_room_id"):
        details = {
            "type": IntentLabel.EDIT_ROOM.value,
            "previous": event_entry.get("locked_room_id"),
            "new": new_room,
        }
        return 3, "confirmation_changed_room", details

    participants = user_info.get("participants")
    req = event_entry.get("requirements") or {}
    if participants and participants != req.get("number_of_participants"):
        details = {
            "type": IntentLabel.EDIT_REQUIREMENTS.value,
            "field": "number_of_participants",
            "previous": req.get("number_of_participants"),
            "new": participants,
        }
        return 3, "confirmation_changed_participants", details

    products_add = user_info.get("products_add")
    products_remove = user_info.get("products_remove")
    if products_add or products_remove:
        details = {
            "type": IntentLabel.EDIT_REQUIREMENTS.value,
            "field": "products",
            "add": products_add,
            "remove": products_remove,
        }
        return 4, "confirmation_changed_products", details

    if intent in {IntentLabel.EDIT_DATE, IntentLabel.EDIT_ROOM, IntentLabel.EDIT_REQUIREMENTS}:
        mapping = {
            IntentLabel.EDIT_DATE: (2, "confirmation_edit_date"),
            IntentLabel.EDIT_ROOM: (3, "confirmation_edit_room"),
            IntentLabel.EDIT_REQUIREMENTS: (3, "confirmation_edit_requirements"),
        }
        target_step, reason = mapping[intent]
        details = {"type": intent.value, "previous": None, "new": None}
        return target_step, reason, details

    return None


def _launch_edit_detour(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    target_step: int,
    reason: str,
    details: Dict[str, Any],
) -> GroupResult:
    acknowledgement = (
        "Got it - let's adjust that. I'll check availability again and refresh your offer, "
        "then bring you back here to confirm."
    )
    state.add_draft_message(
        {"body": acknowledgement, "step": 7, "topic": "confirmation_edit_ack", "requires_approval": True}
    )

    trace_size = _append_edit_trace(event_entry, details)
    thread_state = "In Progress" if target_step == 4 else "Awaiting Client Response"
    update_event_metadata(event_entry, caller_step=7, current_step=target_step, thread_state=thread_state)
    append_audit_entry(event_entry, 7, target_step, reason)
    state.caller_step = 7
    state.current_step = target_step
    state.set_thread_state(thread_state)
    state.extras["persist"] = True
    _record_detour_log(event_entry, reason, details, trace_size)
    edit_type = details.get("type")
    if details.get("field") == "products":
        edit_type = "edit_products"
    state.telemetry.detour_started = True
    state.telemetry.detour_completed = False
    state.telemetry.no_op_detour = details.get("previous") == details.get("new")
    state.telemetry.final_action = edit_type or "none"

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": reason,
        "target_step": target_step,
        "context": state.context_snapshot,
        "persisted": True,
        "edit_details": details,
        "edit_trace_size": trace_size,
    }
    return GroupResult(action="confirmation_detour", payload=payload, halt=False)


def _append_edit_trace(event_entry: Dict[str, Any], details: Dict[str, Any]) -> int:
    trace = event_entry.setdefault("edit_trace", [])
    entry: Dict[str, Any] = {
        "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "type": details.get("type"),
    }
    for key in ("previous", "new", "field", "add", "remove"):
        if details.get(key) is not None:
            entry[key] = details.get(key)
    trace.append(entry)
    return len(trace)


def _record_detour_log(
    event_entry: Dict[str, Any],
    reason: str,
    details: Dict[str, Any],
    trace_size: int,
) -> None:
    logs = event_entry.setdefault("logs", [])
    logs.append(
        {
            "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "actor": "workflow",
            "action": "detour_started",
            "details": {
                "reason": reason,
                "edit": details,
                "edit_trace_size": trace_size,
            },
        }
    )


def _prepare_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
    room_name = event_entry.get("locked_room_id") or event_entry.get("room_pending_decision", {}).get("selected_room")
    event_date = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date")

    update_billing_details(event_entry)
    missing_fields = missing_billing_fields(event_entry)
    if missing_fields:
        prompt = billing_prompt_for_missing_fields(missing_fields)
        draft = {
            "body": prompt,
            "step": 7,
            "topic": "confirmation_billing_missing",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        payload["missing_billing_fields"] = missing_fields
        state.telemetry.final_action = "confirm"
        return GroupResult(action="confirmation_billing_missing", payload=payload, halt=True)

    if deposit_state.get("required") and deposit_state.get("status") != "paid":
        deposit_state["status"] = "requested"
        amount = deposit_state.get("due_amount")
        if amount:
            amount_text = f"CHF {amount:,.2f}".rstrip("0").rstrip(".")
        elif deposit_state.get("percent"):
            amount_text = f"a {deposit_state['percent']}% deposit"
        else:
            amount_text = "the agreed deposit"
        message = (
            f"To finalise your booking, please proceed with the deposit of {amount_text}. "
            "I’ll send payment details now. Once received, I’ll confirm your event officially."
        )
        draft = {
            "body": message,
            "step": 7,
            "topic": "confirmation_deposit_pending",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        conf_state["pending"] = {"kind": "deposit_request"}
        update_event_metadata(event_entry, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        state.telemetry.final_action = "confirm"
        return GroupResult(action="confirmation_deposit_requested", payload=payload, halt=True)

    room_fragment = f" for {room_name}" if room_name else ""
    date_fragment = f" on {event_date}" if event_date else ""
    draft = {
        "body": (
            f"Wonderful — we’re ready to proceed with your booking{room_fragment}{date_fragment}. "
            "I’ll place the booking and send a confirmation message shortly."
        ),
        "step": 7,
        "topic": "confirmation_final",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    conf_state["pending"] = {"kind": "final_confirmation"}
    update_event_metadata(event_entry, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    state.telemetry.final_action = "confirm"
    return GroupResult(action="confirmation_draft", payload=payload, halt=True)


def _handle_deposit_paid(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    deposit_state["status"] = "paid"
    return _prepare_confirmation(state, event_entry)


def _handle_reserve(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    deposit_state = event_entry.setdefault(
        "deposit_state", {"required": False, "percent": 0, "status": "not_required", "due_amount": 0.0}
    )
    deposit_state["required"] = True
    deposit_state["status"] = "requested"
    room_name = event_entry.get("locked_room_id") or event_entry.get("room_pending_decision", {}).get("selected_room")
    event_date = event_entry.get("chosen_date") or event_entry.get("event_data", {}).get("Event Date")
    option_deadline = (
        event_entry.get("reservation_expires_at")
        or event_entry.get("option_valid_until")
        or event_entry.get("reservation_valid_until")
    )
    amount = deposit_state.get("due_amount")
    if amount:
        amount_text = f"CHF {amount:,.2f}".rstrip("0").rstrip(".")
    elif deposit_state.get("percent"):
        amount_text = f"a {deposit_state['percent']}% deposit"
    else:
        amount_text = "the deposit"
    validity_sentence = (
        f"The option is valid until {option_deadline}."
        if option_deadline
        else "The option is valid while we hold the date."
    )
    reservation_text_parts = [
        "We’ve reserved",
        room_name or "the room",
        "on",
        event_date or "the requested date",
        "for you.",
        validity_sentence,
        f"To confirm the booking, please proceed with the deposit of {amount_text}.",
        "I’ll send payment details now.",
    ]
    body = " ".join(part for part in reservation_text_parts if part)
    draft = {
        "body": body,
        "step": 7,
        "topic": "confirmation_reserve",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "reserve_notification"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_reserve", payload=payload, halt=True)


def _handle_site_visit(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    if not site_visit_allowed(event_entry):
        conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
        conf_state["pending"] = None
        return _site_visit_unavailable_response(state, event_entry)

    slots = _generate_visit_slots(event_entry)
    visit_state = event_entry.setdefault(
        "site_visit_state", {"status": "idle", "proposed_slots": [], "scheduled_slot": None}
    )
    visit_state["status"] = "proposed"
    visit_state["proposed_slots"] = slots
    draft_lines = ["We’d be happy to arrange a site visit. Here are some possible times:"]
    draft_lines.extend(f"- {slot}" for slot in slots)
    draft_lines.append("Which would suit you? If you have other preferences, let me know and I’ll try to accommodate.")
    draft = {
        "body": "\n".join(draft_lines),
        "step": 7,
        "topic": "confirmation_site_visit",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "site_visit"
    }
    update_event_metadata(event_entry, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_site_visit", payload=payload, halt=True)


def _site_visit_unavailable_response(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    draft = {
        "body": (
            "Thanks for checking — for this room we aren't able to offer on-site visits before confirmation, "
            "but I'm happy to share additional details or photos."
        ),
        "step": 7,
        "topic": "confirmation_question",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(event_entry, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def _handle_decline(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    event_entry.setdefault("event_data", {})["Status"] = EventStatus.CANCELLED.value
    draft = {
        "body": "Thank you for letting us know. We’ve released the date, and we’d be happy to assist with any future events.",
        "step": 7,
        "topic": "confirmation_decline",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})["pending"] = {
        "kind": "decline"
    }
    update_event_metadata(event_entry, thread_state="In Progress")
    state.set_thread_state("In Progress")
    state.extras["persist"] = True
    state.telemetry.final_action = "discard"
    event_entry["decision"] = "discarded"
    payload = _base_payload(state, event_entry)
    state.telemetry.buttons_enabled = False
    payload["buttons_enabled"] = False
    return GroupResult(action="confirmation_decline", payload=payload, halt=True)


def _handle_question(state: WorkflowState) -> GroupResult:
    draft = {
        "body": "Happy to help — could you share a bit more detail so I can advise?",
        "step": 7,
        "topic": "confirmation_question",
        "requires_approval": True,
    }
    state.add_draft_message(draft)
    update_event_metadata(state.event_entry, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = _base_payload(state, state.event_entry)
    return GroupResult(action="confirmation_question", payload=payload, halt=True)


def _process_hil_confirmation(state: WorkflowState, event_entry: Dict[str, Any]) -> GroupResult:
    conf_state = event_entry.setdefault("confirmation_state", {"pending": None, "last_response_type": None})
    pending = conf_state.get("pending") or {}
    kind = pending.get("kind")

    if not kind:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_confirmation",
            "context": state.context_snapshot,
        }
        return GroupResult(action="confirmation_hil_noop", payload=payload, halt=True)

    if kind == "final_confirmation":
        _ensure_calendar_block(event_entry)
        event_entry.setdefault("event_data", {})["Status"] = EventStatus.CONFIRMED.value
        event_entry["decision"] = "accepted"
        conf_state["pending"] = None
        update_event_metadata(event_entry, transition_ready=True, thread_state="In Progress")
        append_audit_entry(event_entry, 7, 7, "confirmation_sent")
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        state.telemetry.final_action = "accepted"
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_finalized", payload=payload, halt=True)

    if kind == "decline":
        conf_state["pending"] = None
        event_entry["decision"] = "discarded"
        update_event_metadata(event_entry, thread_state="In Progress")
        append_audit_entry(event_entry, 7, 7, "confirmation_declined")
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_decline_sent", payload=payload, halt=True)

    if kind == "site_visit":
        if not site_visit_allowed(event_entry):
            conf_state["pending"] = None
            return _site_visit_unavailable_response(state, event_entry)

        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "site_visit_proposed")
        update_event_metadata(event_entry, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_site_visit_sent", payload=payload, halt=True)

    if kind == "deposit_request":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "deposit_requested")
        update_event_metadata(event_entry, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_deposit_notified", payload=payload, halt=True)

    if kind == "reserve_notification":
        conf_state["pending"] = None
        append_audit_entry(event_entry, 7, 7, "reserve_notified")
        update_event_metadata(event_entry, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        payload = _base_payload(state, event_entry)
        return GroupResult(action="confirmation_reserve_sent", payload=payload, halt=True)

    payload = _base_payload(state, event_entry)
    return GroupResult(action="confirmation_hil_noop", payload=payload, halt=True)


def _generate_visit_slots(event_entry: Dict[str, Any]) -> List[str]:
    base = event_entry.get("chosen_date") or "15.03.2025"
    try:
        day, month, year = map(int, base.split("."))
        anchor = datetime(year, month, day)
    except ValueError:
        anchor = datetime.utcnow()
    slots: List[str] = []
    for offset in range(3):
        candidate = anchor - timedelta(days=offset + 1)
        slot = candidate.replace(hour=10 + offset, minute=0)
        slots.append(slot.strftime("%d.%m.%Y at %H:%M"))
    return slots


def _ensure_calendar_block(event_entry: Dict[str, Any]) -> None:
    blocks = event_entry.setdefault("calendar_blocks", [])
    date_label = event_entry.get("chosen_date") or ""
    room = event_entry.get("locked_room_id") or "Room"
    blocks.append({"date": date_label, "room": room, "created_at": datetime.utcnow().isoformat()})


def _iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%d.%m.%Y")


def _base_payload(state: WorkflowState, event_entry: Dict[str, Any]) -> Dict[str, Any]:
    buttons_enabled, missing_fields, gatekeeper, gate_explain = _sync_gate_context(state, event_entry)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "buttons_rendered": True,
        "buttons_enabled": buttons_enabled,
        "missing_fields": missing_fields,
        "gatekeeper_passed": dict(gatekeeper),
        "gate_explain": gate_explain,
        "gatekeeper_explain": gate_explain,
    }
    return payload


def _sync_gate_context(
    state: WorkflowState, event_entry: Dict[str, Any]
) -> Tuple[bool, List[str], Dict[str, bool], Dict[str, Any]]:
    update_billing_details(event_entry)
    gatekeeper = refresh_gatekeeper(event_entry)
    gate_explain = event_entry.get("gatekeeper_explain") or explain_step7_gate(event_entry)
    missing_now = gate_explain.get("missing_now") or []
    deduped_missing: List[str] = []
    seen: set[str] = set()
    for entry in missing_now:
        if entry not in seen:
            seen.add(entry)
            deduped_missing.append(entry)

    buttons_enabled = bool(gate_explain.get("ready"))

    state.telemetry.buttons_rendered = True
    state.telemetry.buttons_enabled = buttons_enabled
    state.telemetry.missing_fields = deduped_missing
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    state.telemetry.caller_step = state.caller_step or event_entry.get("caller_step")
    state.telemetry.detour_completed = event_entry.get("caller_step") is None
    setattr(state.telemetry, "gate_explain", gate_explain)
    setattr(state.telemetry, "gatekeeper_explain", gate_explain)

    return buttons_enabled, deduped_missing, gatekeeper, gate_explain


def _any_keyword_match(lowered: str, keywords: Tuple[str, ...]) -> bool:
    return any(_contains_word(lowered, keyword) for keyword in keywords)


def _contains_word(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text) is not None
