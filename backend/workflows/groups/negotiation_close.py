from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.domain import TaskType
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.general_qna import append_general_qna_to_primary, _fallback_structured_body
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io.tasks import enqueue_task
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import trace_marker, trace_general_qa_status, set_subloop
from backend.debug.trace import set_hil_open
from backend.utils.profiler import profile_step

__all__ = ["process"]

MAX_COUNTERS = 3

ACCEPT_KEYWORDS = (
    "accept",
    "accepted",
    "confirmed",
    "confirm",
    "looks good",
    "we agree",
    "approved",
    "approve",
    "continue",
    "please send",
    "send it",
    "send to client",
    "ok to send",
    "go ahead",
    "proceed",
    "that's fine",
    "thats fine",
    "fine for me",
    "ok",
    "okay",
    "yes that's fine",
    "yes thats fine",
    "sounds good",
    "good to go",
)
DECLINE_KEYWORDS = ("decline", "reject", "cancel", "not move forward", "no longer", "pass")
COUNTER_KEYWORDS = ("discount", "lower", "reduce", "better price", "could you do", "counter", "budget")


@profile_step("workflow.step5.negotiation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Step 5 — negotiation handling and close preparation."""

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
        return GroupResult(action="negotiation_missing_event", payload=payload, halt=True)

    state.current_step = 5
    thread_id = _thread_id(state)
    negotiation_state = event_entry.setdefault(
        "negotiation_state", {"counter_count": 0, "manual_review_task_id": None}
    )

    # Handle HIL decision callbacks for Step 5 (offer approval/decline).
    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 5:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_negotiation_decision(state, event_entry, decision)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    message_text = (state.message.body or "").strip()
    user_info = state.user_info or {}

    # [CHANGE DETECTION] Run FIRST to detect structural changes
    structural = _detect_structural_change(state.user_info, event_entry)

    if structural:
        # Handle structural change detour BEFORE Q&A
        target_step, reason = structural
        update_event_metadata(event_entry, caller_step=5, current_step=target_step)
        append_audit_entry(event_entry, 5, target_step, reason)
        negotiation_state["counter_count"] = 0
        state.caller_step = 5
        state.current_step = target_step
        if target_step in {2, 3}:
            state.set_thread_state("Awaiting Client")
        else:
            state.set_thread_state("Waiting on HIL")
        state.extras["persist"] = True
        return GroupResult(
            action="structural_change_detour",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "detour_to_step": target_step,
                "caller_step": 5,
                "reason": reason,
                "persisted": True,
            },
            halt=False,
        )

    # [Q&A DETECTION] Check for general Q&A AFTER change detection
    qna_classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = qna_classification
    state.extras["general_qna_detected"] = bool(qna_classification.get("is_general"))

    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if qna_classification["is_general"] else "not_general",
            data={
                "heuristics": qna_classification.get("heuristics"),
                "parsed": qna_classification.get("parsed"),
                "constraints": qna_classification.get("constraints"),
                "llm_called": qna_classification.get("llm_called"),
                "llm_result": qna_classification.get("llm_result"),
                "cached": qna_classification.get("cached"),
            },
            owner_step="Step5_Negotiation",
        )

    classification = _classify_message(message_text)

    # Handle Q&A if detected (after change detection, before negotiation classification)
    general_qna_applicable = qna_classification.get("is_general")
    deferred_general_qna = general_qna_applicable and classification in {"accept", "decline", "counter"}
    if general_qna_applicable and not deferred_general_qna:
        result = _present_general_room_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "accept":
        response = _handle_accept(event_entry)
        state.add_draft_message(response["draft"])
        append_audit_entry(event_entry, 5, 5, "offer_accept_pending_hil")
        negotiation_state["counter_count"] = 0
        update_event_metadata(event_entry, current_step=5, thread_state="Waiting on HIL", transition_ready=False)
        event_entry["negotiation_pending_decision"] = response["pending"]
        state.current_step = 5
        state.set_thread_state("Waiting on HIL")
        set_hil_open(thread_id, True)
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "offer_id": response["offer_id"],
            "pending_decision": response["pending"],
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        result = GroupResult(action="negotiation_accept_pending_hil", payload=payload, halt=True)
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "decline":
        response = _handle_decline(event_entry)
        state.add_draft_message(response)
        append_audit_entry(event_entry, 5, 7, "offer_declined")
        negotiation_state["counter_count"] = 0
        update_event_metadata(event_entry, current_step=7, thread_state="In Progress")
        state.current_step = 7
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        result = GroupResult(action="negotiation_decline", payload=payload, halt=False)
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    if classification == "counter":
        negotiation_state["counter_count"] = int(negotiation_state.get("counter_count") or 0) + 1
        if negotiation_state["counter_count"] > MAX_COUNTERS:
            manual_id = negotiation_state.get("manual_review_task_id")
            if not manual_id:
                manual_payload = {
                    "reason": "negotiation_counter_limit",
                    "message_preview": message_text[:160],
                }
                manual_id = enqueue_task(
                    state.db,
                    TaskType.MANUAL_REVIEW,
                    state.client_id or "",
                    event_entry.get("event_id"),
                    manual_payload,
                )
                negotiation_state["manual_review_task_id"] = manual_id
            draft = {
                "body": append_footer(
                    "Thanks for the suggestions — I’ve escalated this to our manager to review pricing. "
                    "We’ll get back to you shortly.",
                    step=5,
                    next_step=5,
                    thread_state="Awaiting Client Response",
                ),
                "step": 5,
                "topic": "negotiation_manual_review",
                "requires_approval": True,
            }
            state.add_draft_message(draft)
            update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client Response")
            state.set_thread_state("Awaiting Client Response")
            state.extras["persist"] = True
            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "draft_messages": state.draft_messages,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
                "manual_review_task_id": manual_id,
            }
            result = GroupResult(action="negotiation_manual_review", payload=payload, halt=True)
            if deferred_general_qna:
                _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
            return result

        update_event_metadata(event_entry, caller_step=5, current_step=4)
        append_audit_entry(event_entry, 5, 4, "negotiation_counter")
        state.caller_step = 5
        state.current_step = 4
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "counter_count": negotiation_state["counter_count"],
            "context": state.context_snapshot,
            "persisted": True,
        }
        result = GroupResult(action="negotiation_counter", payload=payload, halt=False)
        if deferred_general_qna:
            _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
        return result

    # Clarification by default.
    clarification = {
        "body": append_footer(
            "Happy to clarify any part of the proposal — let me know which detail you’d like more information on.",
            step=5,
            next_step=5,
            thread_state="Awaiting Client Response",
        ),
        "step": 5,
        "topic": "negotiation_clarification",
        "requires_approval": True,
    }
    state.add_draft_message(clarification)
    update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client Response")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    result = GroupResult(action="negotiation_clarification", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, qna_classification, thread_id)
    return result


def _classify_message(message_text: str) -> str:
    lowered = message_text.lower()
    if any(keyword in lowered for keyword in ACCEPT_KEYWORDS):
        return "accept"
    if any(keyword in lowered for keyword in DECLINE_KEYWORDS):
        return "decline"
    if any(keyword in lowered for keyword in COUNTER_KEYWORDS):
        return "counter"
    if re.search(r"\bchf\s*\d", lowered) or re.search(r"\d+\s*(?:franc|price|total)", lowered):
        return "counter"
    if "?" in lowered:
        return "clarification"
    return "clarification"


def _detect_structural_change(user_info: Dict[str, Any], event_entry: Dict[str, Any]) -> Optional[tuple[int, str]]:
    new_iso_date = user_info.get("date")
    new_ddmmyyyy = user_info.get("event_date")
    if new_iso_date or new_ddmmyyyy:
        candidate = new_ddmmyyyy or _iso_to_ddmmyyyy(new_iso_date)
        if candidate and candidate != event_entry.get("chosen_date"):
            return 2, "negotiation_changed_date"

    new_room = user_info.get("room")
    if new_room and new_room != event_entry.get("locked_room_id"):
        return 3, "negotiation_changed_room"

    participants = user_info.get("participants")
    req = event_entry.get("requirements") or {}
    if participants and participants != req.get("number_of_participants"):
        return 3, "negotiation_changed_participants"

    products_add = user_info.get("products_add")
    products_remove = user_info.get("products_remove")
    if products_add or products_remove:
        return 4, "negotiation_changed_products"

    return None


def _apply_hil_negotiation_decision(state: WorkflowState, event_entry: Dict[str, Any], decision: str) -> GroupResult:
    """Process HIL approval/decline for Step 5 offer acceptance."""

    thread_id = _thread_id(state)
    pending = event_entry.get("negotiation_pending_decision")
    if not pending:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_negotiation_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="negotiation_hil_missing", payload=payload, halt=True)

    if decision != "approve":
        event_entry.pop("negotiation_pending_decision", None)
        append_audit_entry(event_entry, 5, 5, "offer_hil_rejected")
        draft = {
            "body": append_footer(
                "Manager declined this offer version. Please adjust and resend.",
                step=5,
                next_step=5,
                thread_state="Awaiting Client",
            ),
            "step": 5,
            "topic": "negotiation_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=5, thread_state="Awaiting Client")
        state.set_thread_state("Awaiting Client")
        set_hil_open(thread_id, False)
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="negotiation_hil_rejected", payload=payload, halt=True)

    # Approval path
    offer_id = pending.get("offer_id") or event_entry.get("current_offer_id")
    offers = event_entry.get("offers") or []
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = timestamp
    event_entry["offer_status"] = "Accepted"
    event_entry.pop("negotiation_pending_decision", None)
    append_audit_entry(event_entry, 5, 6, "offer_accepted_hil")
    update_event_metadata(event_entry, current_step=6, thread_state="In Progress")
    state.current_step = 6
    state.set_thread_state("In Progress")
    set_hil_open(thread_id, False)
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": offer_id,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="negotiation_hil_approved", payload=payload, halt=False)


def _offer_summary_lines(event_entry: Dict[str, Any]) -> list[str]:
    """Build a lightweight offer summary for HIL review."""

    pricing = event_entry.get("pricing_inputs") or {}
    line_items = pricing.get("line_items") or []
    total = pricing.get("total_amount") or pricing.get("total") or 0.0
    try:
        total_val = float(total)
    except (TypeError, ValueError):
        total_val = 0.0

    lines = ["Offer summary:"]
    for item in line_items:
        desc = item.get("description") or item.get("name") or "Item"
        qty = item.get("quantity") or 1
        unit_price = item.get("unit_price") or 0.0
        try:
            unit_val = float(unit_price)
        except (TypeError, ValueError):
            unit_val = 0.0
        amount = qty * unit_val
        lines.append(f"- {qty}× {desc} · CHF {amount:,.2f}")

    lines.append(f"Total: CHF {total_val:,.2f}")
    return lines


def _handle_accept(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pending = {
        "type": "accept",
        "offer_id": offer_id,
        "created_at": timestamp,
    }
    summary_lines = _offer_summary_lines(event_entry)
    draft = {
        "body": append_footer(
            "Client accepted the offer. Please approve to proceed to confirmation.\n\n" + "\n".join(summary_lines),
            step=5,
            next_step=5,
            thread_state="Waiting on HIL",
        ),
        "step": 5,
        "topic": "negotiation_accept",
        "requires_approval": True,
    }
    return {"offer_id": offer_id, "draft": draft, "pending": pending}


def _handle_decline(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offers = event_entry.get("offers") or []
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Declined"
            offer["declined_at"] = timestamp
    event_entry["offer_status"] = "Declined"
    return {
        "body": append_footer(
            "Thank you for letting me know. I’ve noted the cancellation — we’d be happy to help with future events anytime.",
            step=5,
            next_step=7,
            thread_state="In Progress",
        ),
        "step": 5,
        "topic": "negotiation_decline",
        "requires_approval": True,
    }


def _iso_to_ddmmyyyy(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not match:
        return None
    year, month, day = match.groups()
    return f"{day}.{month}.{year}"


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 5 using the same pattern as Step 2."""
    subloop_label = "general_q_a"
    state.extras["subloop"] = subloop_label
    resolved_thread_id = thread_id or state.thread_id

    if thread_id:
        set_subloop(thread_id, subloop_label)

    # Extract fresh from current message (multi-turn Q&A fix)
    message = state.message
    subject = (message.subject if message else "") or ""
    body = (message.body if message else "") or ""
    message_text = f"{subject}\n{body}".strip() or body or subject

    scan = state.extras.get("general_qna_scan")
    # Force fresh extraction for multi-turn Q&A
    ensure_qna_extraction(state, message_text, scan, force_refresh=True)
    extraction = state.extras.get("qna_extraction")

    # Clear stale qna_cache AFTER extraction
    if isinstance(event_entry, dict):
        event_entry.pop("qna_cache", None)

    structured = build_structured_qna_result(state, extraction) if extraction else None

    if structured and structured.handled:
        rooms = structured.action_payload.get("db_summary", {}).get("rooms", [])
        date_lookup: Dict[str, str] = {}
        for entry in rooms:
            iso_date = entry.get("date") or entry.get("iso_date")
            if not iso_date:
                continue
            try:
                parsed = datetime.fromisoformat(iso_date)
            except ValueError:
                try:
                    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
                except ValueError:
                    continue
            label = parsed.strftime("%d.%m.%Y")
            date_lookup.setdefault(label, parsed.date().isoformat())

        candidate_dates = sorted(date_lookup.keys(), key=lambda label: date_lookup[label])[:5]
        actions = [
            {
                "type": "select_date",
                "label": f"Confirm {label}",
                "date": label,
                "iso_date": date_lookup[label],
            }
            for label in candidate_dates
        ]

        body_markdown = (structured.body_markdown or _fallback_structured_body(structured.action_payload)).strip()
        footer_body = append_footer(
            body_markdown,
            step=5,
            next_step=5,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 5,
            "next_step": 5,
            "thread_state": "Awaiting Client",
            "topic": "general_room_qna",
            "candidate_dates": candidate_dates,
            "actions": actions,
            "subloop": subloop_label,
            "headers": ["Availability overview"],
        }

        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            thread_state="Awaiting Client",
            current_step=5,
            candidate_dates=candidate_dates,
        )
        state.set_thread_state("Awaiting Client")
        state.record_subloop(subloop_label)
        state.intent_detail = "event_intake_with_question"
        state.extras["persist"] = True

        # Store minimal last_general_qna context for follow-up detection only
        if extraction and isinstance(event_entry, dict):
            q_values = extraction.get("q_values") or {}
            event_entry["last_general_qna"] = {
                "topic": structured.action_payload.get("qna_subtype"),
                "date_pattern": q_values.get("date_pattern"),
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            }

        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "candidate_dates": candidate_dates,
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "general_qna": True,
            "structured_qna": structured.handled,
            "qna_select_result": structured.action_payload,
            "structured_qna_debug": structured.debug,
            "actions": actions,
        }
        if extraction:
            payload["qna_extraction"] = extraction
        return GroupResult(action="general_rooms_qna", payload=payload, halt=True)

    # Fallback if structured Q&A failed
    fallback_prompt = "[STRUCTURED_QNA_FALLBACK]\nI couldn't load the structured Q&A context for this request. Please review extraction logs."
    draft_message = {
        "step": 5,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 5 Negotiation · Next: 5 Negotiation · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 5,
        "thread_state": "Awaiting Client",
        "headers": ["Availability overview"],
        "requires_approval": False,
        "subloop": subloop_label,
        "actions": [],
        "candidate_dates": [],
    }
    state.add_draft_message(draft_message)
    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=5,
        candidate_dates=[],
    )
    state.set_thread_state("Awaiting Client")
    state.record_subloop(subloop_label)
    state.intent_detail = "event_intake_with_question"
    state.extras["structured_qna_fallback"] = True
    structured_payload = structured.action_payload if structured else {}
    structured_debug = structured.debug if structured else {"reason": "missing_structured_context"}

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": [],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "general_qna": True,
        "structured_qna": False,
        "structured_qna_fallback": True,
        "qna_select_result": structured_payload,
        "structured_qna_debug": structured_debug,
    }
    if extraction:
        payload["qna_extraction"] = extraction
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)


def _append_deferred_general_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> None:
    pre_count = len(state.draft_messages)
    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        return
    appended = append_general_qna_to_primary(state)
    if not appended:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
