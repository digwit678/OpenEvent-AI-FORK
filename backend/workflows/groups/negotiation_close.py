from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.domain import TaskType
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.io.tasks import enqueue_task
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
    negotiation_state = event_entry.setdefault(
        "negotiation_state", {"counter_count": 0, "manual_review_task_id": None}
    )

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    message_text = (state.message.body or "").strip()
    classification = _classify_message(message_text)
    structural = _detect_structural_change(state.user_info, event_entry)

    if structural:
        target_step, reason = structural
        update_event_metadata(event_entry, caller_step=5, current_step=target_step)
        append_audit_entry(event_entry, 5, target_step, reason)
        negotiation_state["counter_count"] = 0
        state.caller_step = 5
        state.current_step = target_step
        if target_step in {2, 3}:
            state.set_thread_state("Awaiting Client Response")
        else:
            state.set_thread_state("In Progress")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": reason,
            "target_step": target_step,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="negotiation_detour", payload=payload, halt=False)

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
