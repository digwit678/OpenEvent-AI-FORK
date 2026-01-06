"""
Step 4 Offer Composition and Recording Functions.

Extracted from step4_handler.py as part of O3 refactoring (Dec 2025).

This module contains:
- build_offer: Render deterministic offer summary for YAML flow harness
- _record_offer: Create and persist offer record
- _determine_offer_total: Compute total amount from products

Usage:
    from .compose import build_offer, _record_offer, _determine_offer_total
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from backend.debug.hooks import trace_db_write
from backend.workflows.common.pricing import derive_room_rate, normalise_rate
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy

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


__all__ = [
    "build_offer",
    "_record_offer",
    "_determine_offer_total",
]
