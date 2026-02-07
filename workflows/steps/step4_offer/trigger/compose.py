"""
Step 4 Offer Composition, Recording, and Finalization.

Extracted from step4_handler.py (O3 refactoring Dec 2025, CQ-3 Feb 2026).

This module contains:
- build_offer: Render deterministic offer summary for YAML flow harness
- _record_offer: Create and persist offer record
- _determine_offer_total: Compute total amount from products
- compose_and_finalize_offer: Full pipeline from pricing through draft message
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from debug.hooks import trace_db_write
from workflows.common.pricing import derive_room_rate, normalise_rate
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from .product_ops import menu_name_set as _menu_name_set, normalise_product_fields as _normalise_product_fields
from ..llm.send_offer_llm import ComposeOffer


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


def _record_offer(
    event_entry: Dict[str, Any],
    pricing_inputs: Dict[str, Any],
    user_info: Dict[str, Any],
    thread_id: str,
) -> Tuple[str, int, float]:
    """Create and persist an offer record in the event entry."""

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


def _determine_offer_total(event_entry: Dict[str, Any], fallback_total: float) -> float:
    """Compute the total amount directly from products for consistency."""

    try:
        display_total = float(fallback_total)
    except (TypeError, ValueError):
        display_total = 0.0

    computed_total = 0.0

    pricing_inputs = event_entry.get("pricing_inputs") or {}
    base_rate = normalise_rate(pricing_inputs.get("base_rate"))
    if base_rate is None:
        base_rate = derive_room_rate(event_entry)
    if base_rate is not None:
        computed_total += base_rate

    for product in event_entry.get("products", []):
        normalized = _normalise_product_fields(product, menu_names=_menu_name_set())
        try:
            quantity = float(normalized.get("quantity") or 0)
            unit_price = float(normalized.get("unit_price") or 0.0)
        except (TypeError, ValueError):
            continue
        computed_total += quantity * unit_price

    if computed_total > 0:
        return round(computed_total, 2)
    return round(display_total, 2)


def compose_and_finalize_offer(
    state,
    event_entry: Dict[str, Any],
    previous_step: int,
    thread_id: str,
    *,
    classification: Dict[str, Any],
    deferred_general_qna: bool,
):
    """Full pipeline: pricing → recording → deposit → summary → verbalization → draft → step advancement.

    Returns ``GroupResult`` with the offer draft prepared.
    """
    import logging
    from workflows.common.billing import format_billing_display
    from workflows.common.pricing import build_deposit_info
    from workflows.common.prompts import verbalize_draft_body
    from workflows.io.database import append_audit_entry, update_event_metadata
    from workflows.io.integration.config import is_hil_all_replies_enabled
    from debug.hooks import trace_state
    from debug.trace import set_hil_open
    from workflow.state import WorkflowStep, write_stage
    from workflows.common.types import GroupResult
    from activity.persistence import log_workflow_activity

    from .pricing import rebuild_pricing_inputs as _rebuild_pricing_inputs
    from .offer_summary import compose_offer_summary as _compose_offer_summary
    from .product_ops import (
        products_ready as _products_ready,
        infer_participant_count as _infer_participant_count,
    )
    from .helpers import _append_deferred_general_qna

    logger = logging.getLogger(__name__)

    # NOTE: Don't clear caller_step here — needed for detour vs normal-flow decision below.
    write_stage(event_entry, current_step=WorkflowStep.STEP_4)
    state.extras["persist"] = True

    pricing_inputs = _rebuild_pricing_inputs(event_entry, state.user_info)
    offer_id, offer_version, total_amount = _record_offer(event_entry, pricing_inputs, state.user_info, thread_id)

    # Attach deposit info based on global deposit configuration
    deposit_config = (state.db.get("config") or {}).get("global_deposit") or {}
    event_date_dt = None
    chosen_date_str = event_entry.get("chosen_date")
    if chosen_date_str:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                event_date_dt = datetime.strptime(chosen_date_str, fmt)
                break
            except (ValueError, TypeError):
                continue
    deposit_info = build_deposit_info(total_amount, deposit_config, event_date=event_date_dt)
    if deposit_info:
        event_entry["deposit_info"] = deposit_info
        deposit_amount = deposit_info.get("deposit_amount", 0)
        deposit_due = deposit_info.get("deposit_due_date", "before event")
        log_workflow_activity(
            event_entry, "deposit_set",
            amount=f"CHF {deposit_amount:,.2f}",
            due_date=deposit_due,
        )

    summary_lines = _compose_offer_summary(event_entry, total_amount, state)
    billing_display = format_billing_display(
        event_entry.get("billing_details") or {},
        (event_entry.get("event_data") or {}).get("Billing Address"),
    )

    # Universal Verbalizer: only verbalize the introduction text
    room = event_entry.get("locked_room_id") or "your preferred room"
    chosen_date = event_entry.get("chosen_date") or "your requested date"
    formatted_date = format_iso_date_to_ddmmyyyy(chosen_date) if chosen_date != "your requested date" else chosen_date
    intro_text = f"Here is your offer for {room} on {formatted_date}."

    verbalized_intro = verbalize_draft_body(
        intro_text,
        step=4,
        topic="offer_intro",
        event_date=formatted_date,
        participants_count=_infer_participant_count(event_entry),
        room_name=room,
    )

    # [HYBRID MESSAGE] Prepend room confirmation / sourcing prefixes
    room_confirmation_prefix = event_entry.pop("room_confirmation_prefix", "")
    sourced_products = event_entry.get("sourced_products") or {}
    sourcing_prefix = sourced_products.get("sourcing_prefix", "")
    combined_prefix = room_confirmation_prefix + sourcing_prefix

    # [TIME WARNING] Include operating hours warning if needed
    time_warning = state.extras.get("time_warning")
    time_warning_suffix = ""
    if time_warning:
        log_workflow_activity(
            event_entry, "time_outside_hours",
            time=f"{state.user_info.get('start_time', '')} - {state.user_info.get('end_time', '')}",
            issue=state.extras.get("time_warning_issue", "outside_hours"),
        )
        time_warning_suffix = f"\n\n---\n**Note:** {time_warning}"
        logger.info("[Step4][TIME_WARNING] Including operating hours warning in offer")

    offer_body_markdown = combined_prefix + verbalized_intro + "\n\n" + "\n".join(summary_lines) + time_warning_suffix

    draft_message = {
        "body_markdown": offer_body_markdown,
        "step": 4,
        "next_step": "Await feedback",
        "thread_state": "Awaiting Client",
        "topic": "offer_draft",
        "offer_id": offer_id,
        "offer_version": offer_version,
        "total_amount": total_amount,
        "requires_approval": is_hil_all_replies_enabled(),
        "table_blocks": [
            {
                "type": "table",
                "header": ["Field", "Value"],
                "rows": [
                    ["Event Date", event_entry.get("chosen_date") or "TBD"],
                    ["Room", event_entry.get("locked_room_id") or "TBD"],
                    ["Billing address", billing_display or "Pending"],
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

    # Detour flow: stay at step 4 awaiting response to regenerated offer.
    # Normal flow: advance to step 5.
    if caller is not None:
        next_step = 4
        append_audit_entry(event_entry, 4, caller, "return_to_caller")
    else:
        next_step = 5

    update_event_metadata(
        event_entry,
        current_step=next_step,
        thread_state="Awaiting Client",
        transition_ready=False,
        caller_step=None,
    )
    state.current_step = next_step
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

    amount_str = f"€{total_amount}" if total_amount else ""
    log_workflow_activity(event_entry, "offer_sent", amount=amount_str)

    result = GroupResult(action="offer_draft_prepared", payload=payload, halt=True)
    if deferred_general_qna:
        _append_deferred_general_qna(state, event_entry, classification, thread_id)
    return result


__all__ = [
    "build_offer",
    "_record_offer",
    "_determine_offer_total",
    "compose_and_finalize_offer",
]
