from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from backend.workflows.common.capture import capture_user_fields, promote_billing_from_captured
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.utils.profiler import profile_step

from ..llm.send_offer_llm import ComposeOffer

__workflow_role__ = "trigger"


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

    capture_user_fields(state, current_step=4, source=state.message.msg_id)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    promote_billing_from_captured(state, event_entry)

    _ensure_products_container(event_entry)
    _apply_product_operations(event_entry, state.user_info)
    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)

    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info)
    event_entry["selected_products"] = [dict(item) for item in event_entry.get("products", [])]
    offer_snapshot = {
        "offer_id": offer_id,
        "version": offer_version,
        "total_amount": total_amount,
        "products": event_entry["selected_products"],
        "pricing_inputs": pricing_inputs,
    }
    offer_hash = hashlib.sha256(
        json.dumps(offer_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    event_entry["offer_hash"] = offer_hash
    summary_lines = _compose_offer_summary(event_entry, total_amount)

    draft_message = {
        "body": "\n".join(summary_lines),
        "step": 4,
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "requires_approval": True,
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
        thread_state="Awaiting Client Response",
        transition_ready=False,
        caller_step=None,
    )
    if caller is not None:
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    state.current_step = 5
    state.caller_step = None
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True

    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "products": list(event_entry.get("products") or []),
        "selected_products": list(event_entry.get("selected_products") or []),
        "offer_hash": offer_hash,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
    }
    return GroupResult(action="offer_draft_prepared", payload=payload, halt=True)


def _ensure_products_container(event_entry: Dict[str, Any]) -> None:
    if "products" not in event_entry or not isinstance(event_entry["products"], list):
        event_entry["products"] = []


def _apply_product_operations(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> None:
    additions = _normalise_products(user_info.get("products_add"))
    removals = _normalise_product_names(user_info.get("products_remove"))

    if additions:
        for item in additions:
            _upsert_product(event_entry["products"], item)

    if removals:
        event_entry["products"] = [item for item in event_entry["products"] if item["name"].lower() not in removals]


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
