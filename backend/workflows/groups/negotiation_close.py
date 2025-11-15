from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.domain import TaskType
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.general_qna import _fallback_structured_body
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io.tasks import enqueue_task
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import trace_marker, trace_general_qa_status, set_subloop
from backend.utils.profiler import profile_step

__all__ = ["process"]

MAX_COUNTERS = 3

ACCEPT_KEYWORDS = ("accept", "confirmed", "confirm", "looks good", "we agree", "approved")
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

    # Handle Q&A if detected (after change detection, before negotiation classification)
    general_qna_applicable = qna_classification.get("is_general")
    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, qna_classification, thread_id)
        return result

    classification = _classify_message(message_text)

    if classification == "accept":
        response = _handle_accept(event_entry)
        state.add_draft_message(response["draft"])
        append_audit_entry(event_entry, 5, 6, "offer_accepted")
        negotiation_state["counter_count"] = 0
        update_event_metadata(event_entry, current_step=6, thread_state="In Progress")
        state.current_step = 6
        state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "offer_id": response["offer_id"],
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="negotiation_accept", payload=payload, halt=False)

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
        return GroupResult(action="negotiation_decline", payload=payload, halt=False)

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
            return GroupResult(action="negotiation_manual_review", payload=payload, halt=True)

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
        return GroupResult(action="negotiation_counter", payload=payload, halt=False)

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
    return GroupResult(action="negotiation_clarification", payload=payload, halt=True)


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


def _handle_accept(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offers = event_entry.get("offers") or []
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = timestamp
    event_entry["offer_status"] = "Accepted"
    draft = {
        "body": append_footer(
            "Fantastic — I’ve noted your acceptance. I’ll lock everything in now and send the final confirmation shortly.",
            step=5,
            next_step=6,
            thread_state="In Progress",
        ),
        "step": 5,
        "topic": "negotiation_accept",
        "requires_approval": True,
    }
    return {"offer_id": offer_id, "draft": draft}


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
            "headers": ["General Q&A"],
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
        "headers": ["General Q&A"],
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
