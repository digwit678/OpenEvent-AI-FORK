from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from backend.config.flags import env_flag
from backend.workflows.common.billing import missing_billing_fields
from backend.workflows.common.capture import capture_user_fields, promote_billing_from_captured
from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.common.gatekeeper import refresh_gatekeeper
from backend.workflows.common.requirements import merge_client_profile
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, update_event_metadata
from backend.workflow.state import WorkflowStep, default_subflow, write_stage
from backend.services.products import check_availability, normalise_product_payload, merge_product_requests
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

    state.current_step = 4
    state.subflow_group = "offer_review"
    write_stage(event_entry, current_step=WorkflowStep.STEP_4, subflow_group="offer_review")

    auto_lock_enabled = env_flag("ALLOW_AUTO_ROOM_LOCK", False)
    locked_room_id = event_entry.get("locked_room_id")
    if not locked_room_id:
        pending_decision = event_entry.get("room_pending_decision") or {}
        summary = pending_decision.get("summary")
        lines: List[str] = [
            "Before I can prepare an offer I need to lock a room.",
            "",
        ]
        if summary:
            lines.append(summary)
            lines.append("")
        lines.extend(
            [
                "NEXT STEP:",
                "Reply with \"reserve <Room Name>\" (e.g., \"reserve Room B\") to secure your preferred room, and I'll generate the offer immediately.",
            ]
        )
        draft_message = {
            "body": "\n".join(line for line in lines if line is not None),
            "step": 4,
            "topic": "lock_required",
            "requires_approval": True,
        }
        state.add_draft_message(draft_message)
        update_event_metadata(
            event_entry,
            current_step=3,
            thread_state="Awaiting Client Response",
            caller_step=4,
        )
        write_stage(
            event_entry,
            current_step=WorkflowStep.STEP_3,
            subflow_group=default_subflow(WorkflowStep.STEP_3),
            caller_step=WorkflowStep.STEP_4,
        )
        state.current_step = 3
        state.caller_step = 4
        state.subflow_group = default_subflow(WorkflowStep.STEP_3)
        state.set_thread_state("Awaiting Client Response")
        state.extras["persist"] = True
        deferred = state.telemetry.setdefault("deferred_intents", [])
        if isinstance(deferred, list) and "room_selection" not in deferred:
            deferred.append("room_selection")
        logs = state.telemetry.setdefault("log_events", [])
        if isinstance(logs, list):
            logs.append(
                {
                    "log": "offer_blocked_no_lock",
                    "allowed": False,
                    "policy_flag": auto_lock_enabled,
                    "intent": state.intent.value if state.intent else "unknown",
                    "selected_room": None,
                    "source_turn_id": state.message.msg_id,
                    "path": "offer.process",
                    "reason": "locked_room_missing",
                }
            )
        gatekeeper = refresh_gatekeeper(event_entry)
        state.telemetry.gatekeeper_passed = dict(gatekeeper)
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
            "gatekeeper_passed": dict(gatekeeper),
        }
        return GroupResult(action="offer_blocked_no_lock", payload=payload, halt=True)

    previous_step = event_entry.get("current_step") or 3

    capture_user_fields(state, current_step=4, source=state.message.msg_id)

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    promote_billing_from_captured(state, event_entry)

    missing_billing = missing_billing_fields(event_entry)

    _ensure_products_container(event_entry)
    requested_products = event_entry.get("requested_products") or []
    if requested_products:
        merged_requests = merge_product_requests(event_entry.get("products"), requested_products)
        if merged_requests != (event_entry.get("products") or []):
            event_entry["products"] = merged_requests
            state.extras["persist"] = True
    _apply_product_operations(event_entry, state.user_info)
    availability_snapshot = check_availability(
        event_entry.get("products") or [],
        locked_room_id,
        _resolve_event_date_iso(event_entry),
    )
    products_state = event_entry.setdefault("products_state", {})
    products_state["availability"] = availability_snapshot
    products_state["missing_items"] = availability_snapshot.get("missing", [])
    products_state["requested_items"] = list(event_entry.get("products") or [])
    event_entry["products"] = [dict(item) for item in availability_snapshot.get("available", [])]
    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)

    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info)
    event_entry["selected_products"] = [dict(item) for item in availability_snapshot.get("available", [])]
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
    summary_lines = _compose_offer_summary(event_entry, total_amount, availability_snapshot, missing_billing)

    draft_message = {
        "body": "\n".join(summary_lines),
        "step": 4,
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "requires_approval": True,
        "actions": ["Confirm Offer", "Change Offer", "Discard Offer"],
        "products_availability": availability_snapshot,
    }
    if availability_snapshot.get("missing"):
        draft_message["manager_special_request"] = True
    if missing_billing:
        draft_message["missing_billing_fields"] = missing_billing
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
    write_stage(event_entry, current_step=WorkflowStep.STEP_5, subflow_group=default_subflow(WorkflowStep.STEP_5))
    if caller is not None:
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    state.current_step = 5
    state.caller_step = None
    state.subflow_group = default_subflow(WorkflowStep.STEP_5)
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
        "products_availability": availability_snapshot,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "gatekeeper_passed": dict(gatekeeper),
    }
    if availability_snapshot.get("missing"):
        payload["manager_special_request"] = True
    if missing_billing:
        payload["missing_billing_fields"] = missing_billing
    return GroupResult(action="offer_draft_prepared", payload=payload, halt=True)


def _ensure_products_container(event_entry: Dict[str, Any]) -> None:
    if "products" not in event_entry or not isinstance(event_entry["products"], list):
        event_entry["products"] = []


def _apply_product_operations(event_entry: Dict[str, Any], user_info: Dict[str, Any]) -> None:
    participant_count = None
    if isinstance(user_info.get("participants"), int):
        participant_count = user_info.get("participants")
    else:
        requirements = event_entry.get("requirements") or {}
        candidate = requirements.get("number_of_participants")
        if isinstance(candidate, int):
            participant_count = candidate
        else:
            try:
                participant_count = int(str(candidate)) if candidate is not None else None
            except (TypeError, ValueError):
                participant_count = None

    additions = _normalise_products(user_info.get("products_add"), participants=participant_count)
    removals = _normalise_product_names(user_info.get("products_remove"))

    if additions:
        for item in additions:
            _upsert_product(event_entry["products"], item)

    if removals:
        event_entry["products"] = [item for item in event_entry["products"] if item["name"].lower() not in removals]


def _normalise_products(payload: Any, participants: Optional[int] = None) -> List[Dict[str, Any]]:
    return normalise_product_payload(payload, participant_count=participants)


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
    event_entry["offer_gate_ready"] = True
    event_entry["transition_ready"] = False

    return offer_id, offer_sequence, total_amount


def _compose_offer_summary(
    event_entry: Dict[str, Any],
    total_amount: float,
    availability: Dict[str, List[Dict[str, Any]]],
    missing_billing: List[str],
) -> List[str]:
    chosen_date = event_entry.get("chosen_date") or "Date TBD"
    room = event_entry.get("locked_room_id") or "Room TBD"
    window = event_entry.get("requested_window") or {}
    timing = ""
    if window.get("start_time") and window.get("end_time"):
        timing = f" {window['start_time']}–{window['end_time']}"

    lines: List[str] = [
        "OFFER:",
        f"- {room} — {chosen_date}{timing}",
    ]
    available_products = availability.get("available") or []
    missing_products = availability.get("missing") or []

    if available_products:
        lines.append("ADD-ONS:")
        for product in available_products:
            name = product.get("name") or "Add-on"
            quantity = product.get("quantity") or 1
            unit_price = float(product.get("unit_price") or 0.0)
            try:
                quantity_val = int(quantity)
            except (TypeError, ValueError):
                quantity_val = 1
            line_total = unit_price * quantity_val
            lines.append(f"- {name} × {quantity_val} — CHF {line_total:,.2f}")
    else:
        lines.append("- No optional add-ons selected.")

    if missing_products:
        lines.append("")
        lines.append("MISSING ITEMS:")
        for missing in missing_products:
            reason = missing.get("reason") or "Currently unavailable."
            lines.append(f"- {missing.get('name', 'Item')} — {reason}")

    if missing_billing:
        lines.append("")
        lines.append("BILLING DETAILS NEEDED:")
        for field in missing_billing:
            lines.append(f"- {_humanize_billing_field(field)}")

    lines.extend(
        [
            "",
            "PRICE:",
            f"- Total: CHF {total_amount:,.2f}",
            "",
            "NEXT STEP:",
            "- Let me know if everything looks good so I can finalize the offer.",
            "- Confirm Offer | Change Offer | Discard Offer",
        ]
    )
    if missing_products:
        lines.insert(-1, "- Ask me to create a manager special request for the missing items.")
    if missing_billing:
        lines.insert(-1, "- Share the missing billing details so I can finalize the offer.")
    return lines


def _humanize_billing_field(field: str) -> str:
    mapping = {
        "name_or_company": "Company or billing name",
        "street": "Street address",
        "postal_code": "Postal code",
        "city": "City",
        "country": "Country",
    }
    return mapping.get(field, field.replace("_", " ").title())


def _resolve_event_date_iso(event_entry: Dict[str, Any]) -> Optional[str]:
    window = event_entry.get("requested_window") or {}
    iso_value = window.get("date_iso")
    if iso_value:
        return iso_value
    chosen_date = event_entry.get("chosen_date")
    if chosen_date:
        return to_iso_date(chosen_date)
    return None
