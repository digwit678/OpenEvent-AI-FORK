from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from backend.workflows.common.requirements import merge_client_profile, requirements_hash
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.general_qna import append_general_qna_to_primary, _fallback_structured_body
from backend.workflows.change_propagation import detect_change_type, route_change_on_updated_variable
from backend.workflows.qna.engine import build_structured_qna_result
from backend.workflows.qna.extraction import ensure_qna_extraction
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.nlu import detect_general_room_query
from backend.debug.hooks import trace_db_write, trace_detour, trace_gate, trace_state, trace_step, trace_marker, trace_general_qa_status, set_subloop
from backend.debug.trace import set_hil_open
from backend.utils.profiler import profile_step
from backend.workflow.state import WorkflowStep, write_stage
from backend.services.products import find_product, normalise_product_payload
from backend.services.rooms import load_room_catalog
from ...negotiation_close import _handle_accept, ACCEPT_KEYWORDS

from ..llm.send_offer_llm import ComposeOffer

__workflow_role__ = "trigger"


@trace_step("Step4_Offer")
@profile_step("workflow.step4.offer")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Step 4 — offer preparation and transmission."""

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
        return GroupResult(action="offer_missing_event", payload=payload, halt=True)

    previous_step = event_entry.get("current_step") or 3
    state.current_step = 4
    thread_id = _thread_id(state)

    # If an acceptance is already awaiting HIL (step 5), do not emit another offer.
    pending_negotiation = event_entry.get("negotiation_pending_decision")
    pending_hil = [
        req for req in (event_entry.get("pending_hil_requests") or []) if req.get("step") == 5
    ]
    if pending_negotiation or pending_hil:
        state.set_thread_state("Waiting on HIL")
        set_hil_open(thread_id, True)
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "pending_decision": pending_negotiation,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
        }
        return GroupResult(action="offer_waiting_hil", payload=payload, halt=True)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    # [CHANGE DETECTION + Q&A] Tap incoming stream BEFORE offer composition to detect client revisions
    message_text = _message_text(state)
    normalized_message_text = _normalize_quotes(message_text)
    user_info = state.user_info or {}

    # Q&A classification
    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    state.extras["general_qna_detected"] = bool(classification.get("is_general"))
    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]

    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step4_Offer",
        )

    # [CHANGE DETECTION] Run BEFORE Q&A dispatch
    change_type = detect_change_type(event_entry, user_info, message_text=message_text)

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=4)

        # Trace logging for parity with Step 2
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 4,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step4_Offer",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        if decision.next_step != 4:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # Clear room lock for date/requirements changes
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                        locked_room_id=None,
                    )

            append_audit_entry(event_entry, 4, decision.next_step, f"{change_type.value}_change_detected")

            # Skip Q&A: return detour signal
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "change_type": change_type.value,
                "detour_to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="change_detour", payload=payload, halt=False)

    # Acceptance (no product/date change) — short-circuit to HIL review
    if _looks_like_offer_acceptance(normalized_message_text):
        negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
        negotiation_state["counter_count"] = 0
        response = _handle_accept(event_entry)

        state.add_draft_message(response["draft"])
        append_audit_entry(event_entry, previous_step, 5, "offer_accept_pending_hil")
        event_entry["negotiation_pending_decision"] = response["pending"]
        update_event_metadata(
            event_entry,
            current_step=5,
            thread_state="Waiting on HIL",
            transition_ready=False,
            caller_step=None,
        )
        state.current_step = 5
        state.caller_step = None
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
        return GroupResult(action="offer_accept_pending_hil", payload=payload, halt=True)

    # No change detected: check if Q&A should be handled
    has_offer_update = _has_offer_update(user_info)
    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general")
    if general_qna_applicable and has_offer_update:
        deferred_general_qna = True
        general_qna_applicable = False
    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, classification, thread_id)
        return result

    requirements = event_entry.get("requirements") or {}
    current_req_hash = event_entry.get("requirements_hash")
    computed_hash = requirements_hash(requirements) if requirements else None
    if computed_hash and computed_hash != current_req_hash:
        update_event_metadata(event_entry, requirements_hash=computed_hash)
        current_req_hash = computed_hash
        state.extras["persist"] = True

    _ensure_products_container(event_entry)
    products_changed = _apply_product_operations(event_entry, state.user_info or {})
    if products_changed:
        state.extras["persist"] = True
    autofilled = _autofill_products_from_preferences(
        event_entry,
        state.user_info or {},
        min_score=0.5,  # TODO(openevent): expose as configurable threshold
    )
    if autofilled:
        state.extras["persist"] = True

    precondition = _evaluate_preconditions(event_entry, current_req_hash, thread_id)
    if precondition:
        code, target = precondition
        if target in (2, 3):
            return _route_to_owner_step(state, event_entry, target, code, thread_id)
        return _handle_products_pending(state, event_entry, code)

    write_stage(event_entry, current_step=WorkflowStep.STEP_4, caller_step=None)
    update_event_metadata(event_entry, caller_step=None)
    state.extras["persist"] = True
    state.caller_step = None

    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)

    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info, thread_id)
    summary_lines = _compose_offer_summary(event_entry, total_amount)

    draft_message = {
        "body_markdown": "\n".join(summary_lines),
        "step": 4,
        "next_step": "Await feedback",
        "thread_state": "Awaiting Client",
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "requires_approval": False,
        "table_blocks": [
            {
                "type": "table",
                "header": ["Field", "Value"],
                "rows": [
                    ["Event Date", event_entry.get("chosen_date") or "TBD"],
                    ["Room", event_entry.get("locked_room_id") or "TBD"],
                    ["Total", f"CHF {total_amount:,.2f}"],
                ],
            }
        ],
        "actions": [
            {
                "type": "send_offer",
                "label": "Send to client",
                "offer_id": offer_id,
            }
        ],
        "headers": ["Offer"],
    }
    state.add_draft_message(draft_message)

    append_audit_entry(event_entry, previous_step, 4, "offer_generated")

    negotiation_state = event_entry.setdefault("negotiation_state", {"counter_count": 0, "manual_review_task_id": None})
    caller = event_entry.get("caller_step")
    if caller != 5:
        negotiation_state["counter_count"] = 0
        negotiation_state["manual_review_task_id"] = None

    update_event_metadata(
        event_entry,
        current_step=5,
        thread_state="Awaiting Client",
        transition_ready=False,
        caller_step=None,
    )
    if caller is not None:
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("Awaiting Client")
    set_hil_open(thread_id, False)
    state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step4_Offer",
        {
            "offer_id": offer_id,
            "offer_version": offer_version,
            "total_amount": total_amount,
            "products_ready": _products_ready(event_entry),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "products": list(event_entry.get("products") or []),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    result = GroupResult(action="offer_draft_prepared", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


def build_offer(event_id: str, room_id: str, date_iso: str, pax: int) -> Dict[str, Any]:
    """Render a deterministic offer summary used by the YAML flow harness."""

    display_date = format_iso_date_to_ddmmyyyy(date_iso) or date_iso
    room_label = room_id.replace("R-", "Room ") if room_id.startswith("R-") else room_id
    body_lines = [
        f"Offer sent for {room_label} on {display_date} for {pax} guests.",
        "The status is Option. Please review and confirm.",
    ]
    body = "\n".join(body_lines)
    assistant_draft = {"headers": ["Offer"], "body": body}
    return {
        "action": "send_reply",
        "event_id": event_id,
        "status": "Option",
        "offer": {
            "room_id": room_id,
            "date": date_iso,
            "pax": pax,
        },
        "res": {
            "assistant_draft": assistant_draft,
            "assistant_draft_text": body,
        },
    }


def _evaluate_preconditions(
    event_entry: Dict[str, Any],
    current_requirements_hash: Optional[str],
    thread_id: str,
) -> Optional[Tuple[str, Union[int, str]]]:
    date_ok = bool(event_entry.get("date_confirmed"))
    trace_gate(thread_id, "Step4_Offer", "P1 date_confirmed", date_ok, {})
    if not date_ok:
        return "P1", 2

    locked_room_id = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")
    p2_ok = (
        locked_room_id
        and current_requirements_hash
        and room_eval_hash
        and current_requirements_hash == room_eval_hash
    )
    trace_gate(
        thread_id,
        "Step4_Offer",
        "P2 room_locked",
        bool(p2_ok),
        {"locked_room_id": locked_room_id, "room_eval_hash": room_eval_hash, "requirements_hash": current_requirements_hash},
    )
    if not p2_ok:
        return "P2", 3

    capacity_ok = _has_capacity(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P3 capacity_confirmed", capacity_ok, {})
    if not capacity_ok:
        return "P3", 3

    products_ok = _products_ready(event_entry)
    trace_gate(thread_id, "Step4_Offer", "P4 products_ready", products_ok, {})
    if not products_ok:
        return "P4", "products"

    return None


def _route_to_owner_step(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    target_step: int,
    reason_code: str,
    thread_id: str,
) -> GroupResult:
    caller_step = WorkflowStep.STEP_4
    target_enum = WorkflowStep(f"step_{target_step}")
    write_stage(event_entry, current_step=target_enum, caller_step=caller_step)

    thread_state = "Awaiting Client" if target_step == 2 else "Waiting on HIL"
    update_event_metadata(event_entry, thread_state=thread_state)
    append_audit_entry(event_entry, 4, target_step, f"offer_gate_{reason_code.lower()}")

    trace_detour(
        thread_id,
        "Step4_Offer",
        _step_name(target_step),
        f"offer_gate_{reason_code.lower()}",
        {},
    )

    state.current_step = target_step
    state.caller_step = caller_step.numeric
    state.set_thread_state(thread_state)
    set_hil_open(thread_id, thread_state == "Waiting on HIL")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "target_step": target_step,
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_detour", payload=payload, halt=False)


def _handle_products_pending(state: WorkflowState, event_entry: Dict[str, Any], reason_code: str) -> GroupResult:
    products_state = event_entry.setdefault("products_state", {})
    first_prompt = not products_state.get("awaiting_client_products")

    if first_prompt:
        products_state["awaiting_client_products"] = True
        prompt = (
            "Before I prepare your tailored proposal, could you share which catering or add-ons you'd like to include? "
            "Let me know if you'd prefer to proceed without extras."
        )
        draft_message = {
            "body_markdown": prompt,
            "step": 4,
            "next_step": "Share preferred products",
            "thread_state": "Awaiting Client",
            "topic": "offer_products_prompt",
            "requires_approval": False,
            "actions": [
                {
                    "type": "share_products",
                    "label": "Provide preferred products",
                }
            ],
        }
        state.add_draft_message(draft_message)
        append_audit_entry(event_entry, 4, 4, "offer_products_prompt")

    write_stage(event_entry, current_step=WorkflowStep.STEP_4)
    update_event_metadata(event_entry, thread_state="Awaiting Client")

    state.current_step = 4
    state.caller_step = event_entry.get("caller_step")
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "missing": [reason_code],
        "thread_state": state.thread_state,
        "draft_messages": state.draft_messages,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="offer_products_pending", payload=payload, halt=True)


def _has_capacity(event_entry: Dict[str, Any]) -> bool:
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    if participants is None:
        participants = (event_entry.get("event_data") or {}).get("Number of Participants")
    if participants is None:
        participants = (event_entry.get("captured") or {}).get("participants")
    try:
        return int(str(participants).strip()) > 0
    except (TypeError, ValueError, AttributeError):
        return False


def _products_ready(event_entry: Dict[str, Any]) -> bool:
    products = event_entry.get("products") or []
    selected = event_entry.get("selected_products") or []
    products_state = event_entry.get("products_state") or {}
    line_items = products_state.get("line_items") or []
    skip_flag = bool(products_state.get("skip_products") or event_entry.get("products_skipped"))
    return bool(products or selected or line_items or skip_flag)


def _ensure_products_container(event_entry: Dict[str, Any]) -> None:
    if "products" not in event_entry or not isinstance(event_entry["products"], list):
        event_entry["products"] = []


def _has_offer_update(user_info: Dict[str, Any]) -> bool:
    update_keys = (
        "products_add",
        "products_remove",
        "products_skip",
        "skip_products",
        "products_none",
        "offer_total_override",
        "room_rate",
        "offer_id",
    )
    return any(bool(user_info.get(key)) for key in update_keys)


def _autofill_products_from_preferences(
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
    *,
    min_score: float = 0.5,
) -> bool:
    products_state = event_entry.setdefault("products_state", {})
    if products_state.get("autofill_applied"):
        return False

    # Prevent autofill if products were already manually selected or modified.
    if _has_offer_update(user_info):
        return False

    existing_products = event_entry.get("products") or []
    if existing_products:
        products_state["autofill_applied"] = True
        return False

    preferences = {}
    event_prefs = event_entry.get("preferences")
    if isinstance(event_prefs, dict):
        preferences = dict(event_prefs)
    elif isinstance(user_info.get("preferences"), dict):
        preferences = dict(user_info["preferences"])
    if not preferences:
        return False

    selected_room = event_entry.get("locked_room_id")
    if not selected_room:
        pending = event_entry.get("room_pending_decision") or {}
        selected_room = pending.get("selected_room")
    if not selected_room:
        return False

    breakdown_map = preferences.get("room_match_breakdown") or {}
    breakdown = breakdown_map.get(selected_room)
    if not isinstance(breakdown, dict):
        return False

    matches_detail = breakdown.get("matches_detail") or []
    matched_names = breakdown.get("matched") or []
    if not matches_detail and matched_names:
        matches_detail = [{"product": name, "wish": None, "score": 1.0} for name in matched_names if name]

    if not matches_detail:
        return False

    participants = _infer_participant_count(event_entry)
    match_threshold = max(0.65, min_score)
    additions: List[Dict[str, Any]] = []
    summary_entries: List[Dict[str, Any]] = []
    included_lower: Set[str] = set()

    for entry in matches_detail:
        product_name = entry.get("product")
        if not product_name:
            continue
        score = float(entry.get("score") or 0.0)
        if score < match_threshold:
            continue
        record = find_product(product_name)
        if not record or _product_unavailable_in_room(record, selected_room):
            continue
        product_key = record.name.strip().lower()
        if product_key in included_lower:
            continue
        item = _build_product_line_from_record(record, participants)
        additions.append(item)
        summary_entries.append(_summarize_product_line(record, entry.get("wish"), score, item))
        included_lower.add(product_key)

    if not additions:
        # No confident matches; keep prompt logic in place.
        return False

    for item in additions:
        _upsert_product(event_entry["products"], item)

    alternatives_payload = _build_alternative_suggestions(
        breakdown.get("alternatives") or [],
        included_lower,
        selected_room,
        min_score=min_score,
    )

    products_state["autofill_summary"] = {
        "matched": summary_entries,
        "alternatives": alternatives_payload["products"],
        "catering_alternatives": alternatives_payload["catering"],
    }
    products_state["autofill_applied"] = True
    return True


def _apply_product_operations(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> bool:
    participant_count = _infer_participant_count(event_entry)
    additions = _normalise_products(
        user_info.get("products_add"),
        participant_count=participant_count,
    )
    removals = _normalise_product_names(user_info.get("products_remove"))
    changes = False

    if additions:
        for item in additions:
            _upsert_product(event_entry["products"], item)
        changes = True

    if removals:
        event_entry["products"] = [item for item in event_entry["products"] if item["name"].lower() not in removals]
        changes = True

    skip_flag = any(bool(user_info.get(key)) for key in ("products_skip", "skip_products", "products_none"))
    if skip_flag:
        products_state = event_entry.setdefault("products_state", {})
        products_state["skip_products"] = True
        changes = True

    if changes:
        products_state = event_entry.setdefault("products_state", {})
        products_state.pop("awaiting_client_products", None)
        summary = products_state.get("autofill_summary")
        if summary is not None:
            # Clear matched entries so the offer summary reflects the explicit product list.
            summary["matched"] = []

    return changes


def _normalise_products(payload: Any, *, participant_count: Optional[int] = None) -> List[Dict[str, Any]]:
    return normalise_product_payload(payload, participant_count=participant_count)


def _normalise_product_names(payload: Any) -> List[str]:
    if not payload:
        return []
    items = payload if isinstance(payload, list) else [payload]
    names: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            name = raw.get("name")
        else:
            name = raw
        text = str(name or "").strip()
        if text:
            names.append(text.lower())
    return names


def _upsert_product(products: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    """Add or update product in the products list. For existing products, increments quantity."""
    for existing in products:
        if existing["name"].lower() == item["name"].lower():
            # Increment quantity instead of replacing it
            existing["quantity"] = existing.get("quantity", 0) + item.get("quantity", 1)
            existing["unit_price"] = item["unit_price"]
            return
    products.append(item)


def _build_product_line_from_record(record: Any, participants: Optional[int]) -> Dict[str, Any]:
    quantity = 1
    if record.unit == "per_person" and participants:
        quantity = max(1, int(participants))
    item: Dict[str, Any] = {
        "name": record.name,
        "quantity": quantity,
        "unit_price": float(record.base_price or 0.0),
    }
    if getattr(record, "product_id", None):
        item["product_id"] = record.product_id
    if getattr(record, "unit", None):
        item["unit"] = record.unit
    if getattr(record, "category", None):
        item["category"] = record.category
    return item


def _summarize_product_line(
    record: Any,
    wish: Optional[str],
    score: float,
    item: Dict[str, Any],
) -> Dict[str, Any]:
    unit_price = float(item.get("unit_price") or 0.0)
    quantity = int(item.get("quantity") or 1)
    total = unit_price * quantity
    return {
        "name": record.name,
        "category": record.category or "General",
        "unit": record.unit,
        "wish": wish,
        "match_pct": int(round(score * 100)),
        "unit_price": unit_price,
        "quantity": quantity,
        "total": round(total, 2),
    }


def _build_alternative_suggestions(
    raw_alternatives: List[Dict[str, Any]],
    included_lower: Set[str],
    room_name: str,
    *,
    min_score: float,
) -> Dict[str, List[Dict[str, Any]]]:
    best_by_product: Dict[str, Dict[str, Any]] = {}
    for entry in raw_alternatives:
        product_name = entry.get("product")
        if not product_name:
            continue
        score = float(entry.get("score") or 0.0)
        if score < min_score:
            continue
        record = find_product(product_name)
        if not record or _product_unavailable_in_room(record, room_name):
            continue
        key = record.name.strip().lower()
        if key in included_lower:
            continue
        stored = best_by_product.get(key)
        if stored and stored["score"] >= score:
            continue
        best_by_product[key] = {
            "name": record.name,
            "category": record.category or "General",
            "unit": record.unit,
            "unit_price": float(record.base_price or 0.0),
            "score": score,
            "wish": entry.get("wish"),
        }

    product_alternatives: List[Dict[str, Any]] = []
    catering_alternatives: List[Dict[str, Any]] = []
    for payload in sorted(best_by_product.values(), key=lambda item: item["score"], reverse=True):
        formatted = {
            "name": payload["name"],
            "category": payload["category"],
            "unit": payload["unit"],
            "unit_price": payload["unit_price"],
            "match_pct": int(round(payload["score"] * 100)),
            "wish": payload.get("wish"),
        }
        category_lower = (payload["category"] or "").strip().lower()
        if category_lower in {"catering", "beverages"}:
            catering_alternatives.append(formatted)
        else:
            product_alternatives.append(formatted)

    return {"products": product_alternatives, "catering": catering_alternatives}


def _infer_participant_count(event_entry: Dict[str, Any]) -> Optional[int]:
    requirements = event_entry.get("requirements") or {}
    participants = requirements.get("number_of_participants")
    if participants is None:
        participants = (event_entry.get("event_data") or {}).get("Number of Participants")
    if participants is None:
        participants = (event_entry.get("captured") or {}).get("participants")
    try:
        return int(str(participants).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _product_unavailable_in_room(record: Any, room_name: str) -> bool:
    aliases = _room_aliases(room_name)
    record_unavailable = {str(entry).strip().lower() for entry in getattr(record, "unavailable_in", [])}
    return any(alias in record_unavailable for alias in aliases)


@lru_cache(maxsize=1)
def _room_alias_map() -> Dict[str, Set[str]]:
    mapping: Dict[str, Set[str]] = {}
    for record in load_room_catalog():
        identifiers = {
            record.name.strip().lower(),
            (record.room_id or record.name).strip().lower(),
        }
        mapping[record.name] = identifiers
    return mapping


def _room_aliases(room_name: str) -> Set[str]:
    lowered = (room_name or "").strip().lower()
    aliases: Set[str] = {lowered}
    for identifiers in _room_alias_map().values():
        if lowered in identifiers:
            aliases |= identifiers
            break
    return aliases


def _rebuild_pricing_inputs(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> Dict[str, Any]:
    pricing_inputs = dict(event_entry.get("pricing_inputs") or {})
    override_total = user_info.get("offer_total_override")

    if "room_rate" in user_info and user_info["room_rate"] is not None:
        try:
            pricing_inputs["base_rate"] = float(user_info["room_rate"])
        except (TypeError, ValueError):
            pricing_inputs["base_rate"] = pricing_inputs.get("base_rate", 0.0)

    line_items: List[Dict[str, Any]] = []
    for product in event_entry.get("products", []):
        line_items.append(
            {
                "description": product["name"],
                "quantity": product["quantity"],
                "unit_price": product["unit_price"],
                "amount": product["quantity"] * product["unit_price"],
            }
        )
    pricing_inputs["line_items"] = line_items
    if override_total is not None:
        try:
            pricing_inputs["total_amount"] = float(override_total)
        except (TypeError, ValueError):
            pricing_inputs.pop("total_amount", None)
    event_entry["pricing_inputs"] = pricing_inputs
    return pricing_inputs


def _record_offer(
    event_entry: Dict[str, Any],
    pricing_inputs: Dict[str, Any],
    user_info: Dict[str, Any],
    thread_id: str,
) -> Tuple[str, int, float]:
    compose = ComposeOffer()
    offer_payload = {
        "offer_ready_to_generate": True,
        "event_id": event_entry.get("event_id") or "unknown-event",
        "pricing_inputs": pricing_inputs,
        "user_info_final": event_entry.get("requirements", {}),
        "selected_room": {"name": event_entry.get("locked_room_id")},
    }
    composed = compose.run(offer_payload)
    offer_id = composed["offer_id"]
    total_amount = composed["total_amount"]

    offer_sequence = int(event_entry.get("offer_sequence") or 0) + 1
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    offers: List[Dict[str, Any]] = event_entry.setdefault("offers", [])
    for existing in offers:
        if existing.get("status") in {"Draft", "Sent"}:
            existing["status"] = "Superseded"
            existing["superseded_at"] = timestamp

    # Reuse offer_id if provided explicitly (e.g., from counter updates) else append sequence token.
    explicit_id = user_info.get("offer_id")
    if explicit_id:
        offer_id = explicit_id
    else:
        offer_id = f"{event_entry.get('event_id')}-OFFER-{offer_sequence}"

    offer_entry = {
        "offer_id": offer_id,
        "version": offer_sequence,
        "status": "Draft",
        "created_at": timestamp,
        "total_amount": total_amount,
        "pricing_inputs": pricing_inputs,
    }
    offers.append(offer_entry)

    event_entry["offer_sequence"] = offer_sequence
    event_entry["current_offer_id"] = offer_id
    event_entry["offer_status"] = "Draft"
    event_entry["transition_ready"] = False

    trace_db_write(
        thread_id,
        "Step4_Offer",
        "db.offers.create",
        {"offer_id": offer_id, "version": offer_sequence, "total": total_amount},
    )

    return offer_id, offer_sequence, total_amount


def _compose_offer_summary(event_entry: Dict[str, Any], total_amount: float) -> List[str]:
    chosen_date = event_entry.get("chosen_date") or "Date TBD"
    room = event_entry.get("locked_room_id") or "Room TBD"
    products = event_entry.get("products") or []
    products_state = event_entry.get("products_state") or {}
    autofill_summary = products_state.get("autofill_summary") or {}
    matched_summary = autofill_summary.get("matched") or []
    product_alternatives = autofill_summary.get("alternatives") or []
    catering_alternatives = autofill_summary.get("catering_alternatives") or []

    intro_room = room if room != "Room TBD" else "your preferred room"
    intro_date = chosen_date if chosen_date != "Date TBD" else "your requested date"
    lines = [
        f"Great — {intro_room} on {intro_date} is ready for review.",
        f"Offer draft for {chosen_date} · {room}",
    ]

    lines.append("")
    if matched_summary:
        lines.append("**Included products**")
        for entry in matched_summary:
            quantity = int(entry.get("quantity") or 1)
            name = entry.get("name") or "Unnamed item"
            unit_price = float(entry.get("unit_price") or 0.0)
            total_line = float(entry.get("total") or quantity * unit_price)
            unit = entry.get("unit")
            wish = entry.get("wish")

            price_text = f"CHF {total_line:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"

            details: List[str] = []
            if entry.get("match_pct") is not None:
                details.append(f"match {entry.get('match_pct')}%")
            if wish:
                details.append(f'for "{wish}"')
            detail_text = f" ({', '.join(details)})" if details else ""

            lines.append(f"- {quantity}× {name}{detail_text} · {price_text}")

    elif products:
        lines.append("**Included products**")
        for product in products:
            quantity = int(product.get("quantity") or 1)
            name = product.get("name") or "Unnamed item"
            unit_price = float(product.get("unit_price") or 0.0)
            unit = product.get("unit")

            price_text = f"CHF {unit_price * quantity:,.2f}"
            if unit == "per_person" and quantity > 0:
                price_text += f" (CHF {unit_price:,.2f} per person)"

            lines.append(f"- {quantity}× {name} · {price_text}")
    else:
        lines.append("No optional products selected yet.")

    display_total = _determine_offer_total(event_entry, total_amount)

    lines.extend([
        "",
        "---",
        f"**Total: CHF {display_total:,.2f}**",
        "---",
        "",
    ])

    has_alternatives = product_alternatives or catering_alternatives
    if has_alternatives:
        lines.append("**Suggestions for you**")
        lines.append("")

    if product_alternatives:
        lines.append("*Other close matches you can add:*")
        for entry in product_alternatives:
            name = entry.get("name") or "Unnamed add-on"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit = entry.get("unit")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            price_text = f"CHF {unit_price:,.2f}"
            if unit == "per_person":
                price_text += " per person"

            qualifiers: List[str] = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            qualifier_text = f" ({', '.join(qualifiers)})" if qualifiers else ""

            lines.append(f"- {name}{qualifier_text} · {price_text}")
        if catering_alternatives:
            lines.append("")

    if catering_alternatives:
        lines.append("*Catering alternatives with a close fit:*")
        for entry in catering_alternatives:
            name = entry.get("name") or "Catering option"
            unit_price = float(entry.get("unit_price") or 0.0)
            unit_label = (entry.get("unit") or "per event").replace("_", " ")
            wish = entry.get("wish")
            match_pct = entry.get("match_pct")

            qualifiers: List[str] = []
            if match_pct is not None:
                qualifiers.append(f"{match_pct}% match")
            if wish:
                qualifiers.append(f'covers "{wish}"')
            detail = ", ".join(qualifiers)
            detail_text = f" ({detail})" if detail else ""

            lines.append(f"- {name}{detail_text} · CHF {unit_price:,.2f} {unit_label}")

    if has_alternatives:
        lines.append("")

    lines.append("Please review and approve before sending to the manager.")
    return lines


def _determine_offer_total(event_entry: Dict[str, Any], fallback_total: float) -> float:
    """Compute the total amount directly from products for consistency."""

    try:
        display_total = float(fallback_total)
    except (TypeError, ValueError):
        display_total = 0.0

    computed_total = 0.0

    pricing_inputs = event_entry.get("pricing_inputs") or {}
    base_rate = pricing_inputs.get("base_rate")
    if base_rate not in (None, ""):
        try:
            computed_total += float(base_rate)
        except (TypeError, ValueError):
            pass

    for product in event_entry.get("products", []):
        try:
            quantity = float(product.get("quantity") or 0)
            unit_price = float(product.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            continue
        computed_total += quantity * unit_price

    if computed_total > 0:
        return round(computed_total, 2)
    return round(display_total, 2)


def _step_name(step: int) -> str:
    mapping = {
        1: "Step1_Intake",
        2: "Step2_Date",
        3: "Step3_Room",
        4: "Step4_Offer",
        5: "Step5_Negotiation",
        6: "Step6_Transition",
        7: "Step7_Confirmation",
    }
    return mapping.get(step, f"Step{step}")


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state."""
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _normalize_quotes(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "’": "'",
        "‘": "'",
        "´": "'",
        "`": "'",
        "“": '"',
        "”": '"',
    }
    for bad, repl in replacements.items():
        text = text.replace(bad, repl)
    return text


def _looks_like_offer_acceptance(message_text: str) -> bool:
    normalized = _normalize_quotes(message_text or "").lower()
    return any(keyword in normalized for keyword in ACCEPT_KEYWORDS)


def _present_general_room_qna(
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: Optional[str],
) -> GroupResult:
    """Handle general Q&A at Step 4 using the same pattern as Step 2."""
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
            step=4,
            next_step=4,
            thread_state="Awaiting Client",
        )

        draft_message = {
            "body": footer_body,
            "body_markdown": body_markdown,
            "step": 4,
            "next_step": 4,
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
            current_step=4,
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
        "step": 4,
        "topic": "general_room_qna",
        "body": f"{fallback_prompt}\n\n---\nStep: 4 Offer · Next: 4 Offer · State: Awaiting Client",
        "body_markdown": fallback_prompt,
        "next_step": 4,
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
        current_step=4,
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
