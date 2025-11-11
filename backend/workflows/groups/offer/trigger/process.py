from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.workflows.common.requirements import merge_client_profile, requirements_hash
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.debug.hooks import trace_db_write, trace_detour, trace_gate, trace_state, trace_step
from backend.debug.trace import set_hil_open
from backend.utils.profiler import profile_step
from backend.workflow.state import WorkflowStep, write_stage

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

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

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
        "requires_approval": True,
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
    return GroupResult(action="offer_draft_prepared", payload=payload, halt=True)


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
            "requires_approval": True,
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


def _apply_product_operations(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> bool:
    additions = _normalise_products(user_info.get("products_add"))
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

    return changes


def _normalise_products(payload: Any) -> List[Dict[str, Any]]:
    if not payload:
        return []
    normalised: List[Dict[str, Any]] = []
    items = payload if isinstance(payload, list) else [payload]
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        try:
            quantity = int(entry.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        try:
            unit_price = float(entry.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            unit_price = 0.0
        if quantity <= 0 and unit_price <= 0:
            continue
        normalised.append({"name": name, "quantity": max(1, quantity), "unit_price": max(0.0, unit_price)})
    return normalised


def _normalise_product_names(payload: Any) -> List[str]:
    if not payload:
        return []
    names = payload if isinstance(payload, list) else [payload]
    return [str(name).strip().lower() for name in names if str(name).strip()]


def _upsert_product(products: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    for existing in products:
        if existing["name"].lower() == item["name"].lower():
            existing["quantity"] = item["quantity"]
            existing["unit_price"] = item["unit_price"]
            return
    products.append(item)


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

    lines = [
        f"Offer draft for {chosen_date} · {room}",
        f"Total: CHF {total_amount:,.2f}",
    ]
    if products:
        lines.append("Included products:")
        for product in products:
            lines.append(
                f"- {product['name']} × {product['quantity']} @ CHF {product['unit_price']:,.2f}"
            )
    else:
        lines.append("No optional products selected yet.")
    lines.append("Please review and approve before sending to the client.")
    return lines


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
