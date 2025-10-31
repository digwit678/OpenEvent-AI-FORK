from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain import TaskType
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

_ACCEPT_PHRASES = (
    "confirm",
    "confirmed",
    "approve",
    "approved",
    "accept",
    "accepted",
    "we ll take",
    "we will take",
    "go ahead",
    "proceed",
    "lock it in",
    "lock it",
    "lock in",
    "book it",
    "looks good",
    "sounds good",
    "bestätigen",
    "bestätigt",
    "passt",
    "nehmen wir",
    "wir nehmen",
    "buchen",
    "buchen wir",
    "einverstanden",
    "genehmigt",
    "freigeben",
)

_NEGATING_PREFIXES = (
    "can you",
    "could you",
    "would you",
    "please",
    "kannst du",
    "würdest du",
    "kannst ihr",
    "könnt ihr",
    "we can",
    "we could",
    "can we",
    "could we",
)

_CONDITIONAL_TOKENS = ("if", "when", "unless", "falls", "wenn")

_DETAIL_KEYWORDS = (
    "billing",
    "invoice",
    "company",
    "address",
    "contact",
    "email",
    "phone",
    "vat",
    "tax number",
    "steuer",
    "rechnung",
)

_DETAIL_ACTION_VERBS = (
    "update",
    "use",
    "set",
    "change",
    "correct",
    "apply",
    "replace",
    "revise",
    "note",
    "adjust",
)

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
    pending_acceptance = bool(negotiation_state.get("pending_acceptance"))

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    message_text = (state.message.body or "").strip()
    structural = _detect_structural_change(state.user_info, event_entry)
    if not structural:
        structural = _detect_profile_update(message_text)
    if structural:
        classification = "counter"
    else:
        pending_ready = pending_acceptance and not _acceptance_invariants(event_entry)
        if pending_ready:
            classification = "accept"
        elif _detect_accept(message_text):
            classification = "accept"
        elif _detect_decline(message_text):
            classification = "decline"
        elif _detect_counter(message_text):
            classification = "counter"
        else:
            classification = "clarification"
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
        missing = _acceptance_invariants(event_entry)
        if missing:
            draft = _build_acceptance_missing_draft(missing)
            state.add_draft_message(draft)
            state.telemetry.missing_fields = list(missing)
            state.telemetry.final_action = "needs_details"
            update_event_metadata(event_entry, current_step=6, thread_state="Awaiting Client Response")
            state.current_step = 6
            state.set_thread_state("Awaiting Client Response")
            state.extras["persist"] = True
            negotiation_state["pending_acceptance"] = True
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
            return GroupResult(action="transition_blocked", payload=payload, halt=True)

        response = _handle_accept(event_entry)
        state.add_draft_message(response["draft"])
        event_entry["offer_gate_ready"] = False
        append_audit_entry(event_entry, 5, 6, "offer_accepted")
        negotiation_state["counter_count"] = 0
        negotiation_state["pending_acceptance"] = False
        update_event_metadata(event_entry, current_step=6, thread_state="In Progress")
        state.current_step = 6
        state.set_thread_state("In Progress")
        state.telemetry.final_action = "accepted"
        state.telemetry.buttons_rendered = True
        state.telemetry.buttons_enabled = True
        state.extras["persist"] = True
        task_payload = {
            "reason": "offer_accepted",
            "offer_id": response["offer_id"],
            "total_amount": response.get("total_amount"),
            "room": event_entry.get("locked_room_id"),
            "date": event_entry.get("chosen_date"),
        }
        task_id = enqueue_task(
            state.db,
            TaskType.ROUTE_POST_OFFER,
            state.client_id or "",
            event_entry.get("event_id"),
            task_payload,
        )
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
            "send_offer_task_id": task_id,
            "buttons_rendered": True,
            "buttons_enabled": True,
        }
        return GroupResult(action="negotiation_accept", payload=payload, halt=False)

    if classification == "decline":
        response = _handle_decline(event_entry)
        state.add_draft_message(response)
        state.telemetry.buttons_rendered = True
        state.telemetry.buttons_enabled = False
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
            "buttons_rendered": True,
            "buttons_enabled": False,
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
                "body": (
                    "Thanks for the suggestions — I’ve escalated this to our manager to review pricing. "
                    "We’ll get back to you shortly."
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
        "body": (
            "Happy to clarify any part of the proposal — let me know which detail you’d like more information on."
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


def _acceptance_invariants(event_entry: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not (event_entry.get("chosen_date")):
        missing.append("date")
    if not event_entry.get("date_confirmed"):
        missing.append("date_confirmation")
    if not event_entry.get("locked_room_id"):
        missing.append("room")
    return missing


def _build_acceptance_missing_draft(missing: List[str]) -> Dict[str, Any]:
    lines: List[str] = []
    if "date" in missing or "date_confirmation" in missing:
        lines.append("We still need a confirmed event date before I can finalise everything.")
    if "room" in missing:
        lines.append("Let me know which room you'd like me to lock so I can complete the paperwork.")
    if not lines:
        lines.append("Share the remaining details and I'll finalise the offer right away.")
    info = "INFO:\n" + "\n".join(f"- {entry}" for entry in lines)
    next_step = "NEXT STEP:\n- Share the missing details so I can finalise the offer."
    body = f"{info}\n\n{next_step}"
    return {
        "body": body,
        "step": 5,
        "topic": "negotiation_missing_details",
        "requires_approval": True,
    }


def _handle_accept(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    offers = event_entry.get("offers") or []
    offer_id = event_entry.get("current_offer_id")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    total_amount = None
    for offer in offers:
        if offer.get("offer_id") == offer_id:
            offer["status"] = "Accepted"
            offer["accepted_at"] = timestamp
            total_amount = offer.get("total_amount")
    event_entry["offer_status"] = "Accepted"
    draft = {
        "body": (
            "Thank you for confirming — I'll finalise the paperwork now."
            "\n\nNEXT STEP:\n- We’ll prepare the final offer for approval and sending."
        ),
        "step": 5,
        "topic": "negotiation_accept",
        "requires_approval": True,
    }
    return {"offer_id": offer_id, "draft": draft, "total_amount": total_amount}


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
        "body": "Thank you for letting me know. I’ve noted the cancellation — we’d be happy to help with future events anytime.",
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

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _has_negating_prefix(norm_text: str, start_idx: int) -> bool:
    prefix = norm_text[:start_idx].strip()
    if not prefix:
        return False
    tokens = prefix.split()
    if tokens and tokens[-1] in _CONDITIONAL_TOKENS:
        return True
    if len(tokens) >= 2 and " ".join(tokens[-2:]) in {"if we", "if you", "wenn wir", "wenn du"}:
        return True
    last_two = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""
    last_three = " ".join(tokens[-3:]) if len(tokens) >= 3 else ""
    if last_two in _NEGATING_PREFIXES or last_three in _NEGATING_PREFIXES:
        return True
    last_one = tokens[-1]
    return last_one in _NEGATING_PREFIXES


def _has_conditional_suffix(norm_text: str, end_idx: int) -> bool:
    remainder = norm_text[end_idx:].strip()
    if not remainder:
        return False
    words = remainder.split()
    if not words:
        return False
    first_two = " ".join(words[:2])
    if words[0] in _CONDITIONAL_TOKENS or first_two in {"if we", "if you", "wenn wir", "wenn du"}:
        return True
    for token in _CONDITIONAL_TOKENS:
        if f" {token} " in remainder:
            return True
    return False


def _has_word_boundaries(norm_text: str, start_idx: int, end_idx: int) -> bool:
    before_ok = start_idx == 0 or norm_text[start_idx - 1] == " "
    after_ok = end_idx == len(norm_text) or norm_text[end_idx] == " "
    return before_ok and after_ok


def _detect_profile_update(message_text: str) -> Optional[tuple[int, str]]:
    raw = message_text or ""
    norm = _normalize_text(raw)
    if not norm:
        return None
    if any(keyword in norm for keyword in _DETAIL_KEYWORDS):
        if any(verb in norm for verb in _DETAIL_ACTION_VERBS):
            has_numeric = any(ch.isdigit() for ch in raw)
            has_email = "@" in raw
            if has_numeric or has_email:
                return 4, "negotiation_updated_details"
    return None


def _detect_accept(message_text: str) -> bool:
    norm = _normalize_text(message_text)
    if not norm:
        return False
    for phrase in _ACCEPT_PHRASES:
        idx = norm.find(phrase)
        while idx != -1:
            end_idx = idx + len(phrase)
            if (
                _has_word_boundaries(norm, idx, end_idx)
                and not _has_negating_prefix(norm, idx)
                and not _has_conditional_suffix(norm, end_idx)
            ):
                return True
            idx = norm.find(phrase, end_idx)
    return False


def _detect_decline(message_text: str) -> bool:
    norm = _normalize_text(message_text)
    if not norm:
        return False
    for keyword in DECLINE_KEYWORDS:
        if keyword in norm:
            return True
    return False


def _detect_counter(message_text: str) -> bool:
    norm = _normalize_text(message_text)
    if not norm:
        return False
    for keyword in COUNTER_KEYWORDS:
        if keyword in norm:
            return True
    if re.search(r"\b\d+\s*(?:percent|%|personen|gäste)\b", norm):
        return True
    lowered = message_text.lower()
    if re.search(r"\bchf\s*\d", lowered):
        return True
    if re.search(r"\d+\s*(?:franc|price|total)", lowered):
        return True
    return False
