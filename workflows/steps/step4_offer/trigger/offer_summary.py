"""
Step 4 Offer Summary Composition.

Extracted from step4_handler.py as part of god-file refactoring (Jan 2026).

This module contains:
- compose_offer_summary: Build markdown offer summary for client display
- default_menu_alternatives: Generate default catering suggestions

Usage:
    from .offer_summary import compose_offer_summary, default_menu_alternatives
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from workflows.common.billing import format_billing_display
from workflows.common.pricing import derive_room_rate, normalise_rate
from workflows.common.menu_options import DINNER_MENU_OPTIONS
from workflows.common.types import WorkflowState
from utils.pseudolinks import generate_catering_catalog_link, generate_catering_menu_link
from utils.page_snapshots import create_snapshot

from .compose import _determine_offer_total
from .product_ops import (
    menu_name_set as _menu_name_set,
    normalise_product_fields as _normalise_product_fields,
)


def compose_offer_summary(
    event_entry: Dict[str, Any],
    total_amount: float,
    state: WorkflowState,
) -> List[str]:
    """Build markdown offer summary lines for client display.

    Composes a complete offer summary including:
    - Event date and room
    - Contact and billing information
    - Room booking rate
    - Included products with pricing
    - Total amount
    - Deposit information (if applicable)
    - Catering alternatives and suggestions

    Args:
        event_entry: The event database entry
        total_amount: Fallback total amount
        state: Workflow state with extras for Q&A extraction

    Returns:
        List of markdown lines for the offer summary
    """
    chosen_date = event_entry.get("chosen_date") or "Date TBD"
    room = event_entry.get("locked_room_id") or "Room TBD"
    link_date = event_entry.get("chosen_date") or (chosen_date if chosen_date != "Date TBD" else "")
    event_data = event_entry.get("event_data") or {}
    billing_details = event_entry.get("billing_details") or {}
    billing_address = format_billing_display(billing_details, event_data.get("Billing Address"))
    pricing_inputs = event_entry.get("pricing_inputs") or {}

    # Build contact parts
    contact_parts = [
        part.strip()
        for part in (event_data.get("Name"), event_data.get("Company"))
        if isinstance(part, str) and part.strip() and part.strip().lower() != "not specified"
    ]
    email = (event_data.get("Email") or "").strip() or None
    if email and email.lower() != "not specified":
        contact_parts.append(email)

    # Get products and alternatives
    products = event_entry.get("products") or []
    products_state = event_entry.get("products_state") or {}
    autofill_summary = products_state.get("autofill_summary") or {}
    matched_summary = autofill_summary.get("matched") or []
    product_alternatives = autofill_summary.get("alternatives") or []
    catering_alternatives = autofill_summary.get("catering_alternatives") or []
    if not catering_alternatives and not event_entry.get("selected_catering"):
        catering_alternatives = default_menu_alternatives(event_entry)

    # Clear alternatives when user explicitly skipped products
    if products_state.get("skip_products") or event_entry.get("products_skipped"):
        product_alternatives = []
        catering_alternatives = []

    # Extract Q&A parameters for catering catalog link
    qna_extraction = state.extras.get("qna_extraction", {})
    q_values = qna_extraction.get("q_values", {})
    query_params: Dict[str, str] = {}

    if q_values.get("date_pattern"):
        query_params["month"] = str(q_values["date_pattern"]).lower()

    product_attrs = q_values.get("product_attributes") or []
    if isinstance(product_attrs, list):
        for attr in product_attrs:
            attr_lower = str(attr).lower()
            if "vegetarian" in attr_lower:
                query_params["vegetarian"] = "true"
            if "vegan" in attr_lower:
                query_params["vegan"] = "true"
            if "wine" in attr_lower or "pairing" in attr_lower:
                query_params["wine_pairing"] = "true"
            if ("three" in attr_lower or "3" in attr_lower) and "course" in attr_lower:
                query_params["courses"] = "3"

    # Build intro lines
    intro_room = room if room != "Room TBD" else "your preferred room"
    intro_date = chosen_date if chosen_date != "Date TBD" else "your requested date"
    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))

    if manager_requested:
        lines = [
            f"Great, {intro_room} on {intro_date} is ready for manager review.",
            f"Offer draft for {chosen_date} · {room}",
        ]
    else:
        lines = [f"Offer draft for {chosen_date} · {room}"]

    # Add contact and billing info
    spacer_added = False
    if contact_parts or billing_address:
        lines.append("")
        if contact_parts:
            lines.append("Client: " + " · ".join(contact_parts))
        if billing_address:
            lines.append("")
            lines.append(f"Billing address: {billing_address}")
        lines.append("")
        spacer_added = True

    # Add room rate
    room_rate = normalise_rate(pricing_inputs.get("base_rate"))
    if room_rate is None:
        room_rate = derive_room_rate(event_entry)
    if room_rate is not None:
        if not spacer_added:
            lines.append("")
        lines.append("**Room booking**")
        lines.append(f"- {room} · CHF {room_rate:,.2f}")
        spacer_added = True

    # Add products section
    lines.append("")
    if matched_summary:
        lines.append("**Included products**")
        for entry in matched_summary:
            lines.append(_format_matched_product(entry))
    elif products:
        lines.append("**Included products**")
        for product in products:
            lines.append(_format_product(product))
    else:
        lines.append("No optional products selected yet.")

    # Add total
    display_total = _determine_offer_total(event_entry, total_amount)
    lines.extend([
        "",
        "---",
        f"**Total: CHF {display_total:,.2f}**",
    ])

    # Add deposit info if applicable
    deposit_info = event_entry.get("deposit_info") or {}
    deposit_required = deposit_info.get("deposit_required", False)
    deposit_amount = deposit_info.get("deposit_amount")
    deposit_due_date = deposit_info.get("deposit_due_date")

    if deposit_required and deposit_amount:
        lines.append("")
        lines.append(f"**Deposit to reserve: CHF {deposit_amount:,.2f}** (required before confirmation)")
        if deposit_due_date:
            try:
                due_dt = datetime.strptime(deposit_due_date, "%Y-%m-%d")
                formatted_due_date = due_dt.strftime("%d %B %Y")
            except (ValueError, TypeError):
                formatted_due_date = deposit_due_date
            lines.append("")
            lines.append(f"**Deposit due by:** {formatted_due_date}")

    lines.extend(["---", ""])

    # Add catering catalog section
    selected_catering = event_entry.get("selected_catering")
    products_skipped = products_state.get("skip_products") or event_entry.get("products_skipped")
    if not selected_catering and catering_alternatives and not products_skipped:
        _append_catering_catalog(lines, catering_alternatives, room, link_date, query_params, state)
        catering_alternatives = []

    # Add alternatives section
    has_alternatives = product_alternatives or catering_alternatives
    if has_alternatives:
        lines.append("**Suggestions for you**")
        lines.append("")

    if product_alternatives:
        _append_product_alternatives(lines, product_alternatives)
        if catering_alternatives:
            lines.append("")

    if catering_alternatives:
        _append_catering_alternatives(lines, catering_alternatives)

    if has_alternatives:
        lines.append("")

    # Add closing line
    if manager_requested:
        lines.append("Please review and approve before sending to the manager.")
    else:
        lines.append("Please review and approve to confirm.")

    return lines


def default_menu_alternatives(event_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return default dinner menu options as catering suggestions.

    Args:
        event_entry: The event database entry (used to get participant count)

    Returns:
        List of menu alternative dicts with name, unit_price, unit, etc.
    """
    results: List[Dict[str, Any]] = []
    participants = event_entry.get("event_data", {}).get("Number of Participants")
    try:
        participants = int(participants) if participants is not None else None
    except (TypeError, ValueError):
        participants = None

    for menu in DINNER_MENU_OPTIONS:
        name = menu.get("menu_name")
        if not name:
            continue
        price = menu.get("price")
        try:
            unit_price = float(str(price).replace("CHF", "").strip())
        except (TypeError, ValueError):
            unit_price = None
        results.append(
            {
                "name": name,
                "unit_price": unit_price or 0.0,
                "unit": "per_event",
                "wish": "menu",
                "match_pct": 90,
                "quantity": 1,
            }
        )
    return results


# ============================================================
# Helper functions for formatting
# ============================================================

def _format_matched_product(entry: Dict[str, Any]) -> str:
    """Format a matched product entry as a markdown line."""
    normalized = _normalise_product_fields(entry, menu_names=_menu_name_set())
    quantity = int(normalized.get("quantity") or 1)
    name = normalized.get("name") or "Unnamed item"
    unit_price = float(normalized.get("unit_price") or 0.0)
    unit = normalized.get("unit")
    total_line = float(entry.get("total") or quantity * unit_price)
    wish = entry.get("wish")

    price_text = f"CHF {total_line:,.2f}"
    if unit == "per_person" and quantity > 0:
        price_text += f" (CHF {unit_price:,.2f} per person)"
    elif unit == "per_event":
        price_text += " (per event)"

    details: List[str] = []
    if entry.get("match_pct") is not None:
        details.append(f"match {entry.get('match_pct')}%")
    if wish:
        details.append(f'for "{wish}"')
    detail_text = f" ({', '.join(details)})" if details else ""

    return f"- {quantity}× {name}{detail_text} · {price_text}"


def _format_product(product: Dict[str, Any]) -> str:
    """Format a product entry as a markdown line."""
    normalized = _normalise_product_fields(product, menu_names=_menu_name_set())
    quantity = int(normalized.get("quantity") or 1)
    name = normalized.get("name") or "Unnamed item"
    unit_price = float(normalized.get("unit_price") or 0.0)
    unit = normalized.get("unit")

    price_text = f"CHF {unit_price * quantity:,.2f}"
    if unit == "per_person" and quantity > 0:
        price_text += f" (CHF {unit_price:,.2f} per person)"
    elif unit == "per_event":
        price_text += " (per event)"

    return f"- {quantity}× {name} · {price_text}"


def _append_catering_catalog(
    lines: List[str],
    catering_alternatives: List[Dict[str, Any]],
    room: str,
    link_date: str,
    query_params: Dict[str, str],
    state: WorkflowState,
) -> None:
    """Append catering catalog section to lines."""
    catalog_snapshot_data = {
        "catering_alternatives": [dict(e) for e in catering_alternatives],
        "room": room,
        "date": link_date,
        "query_params": query_params,
    }
    catalog_snapshot_id = create_snapshot(
        snapshot_type="catering_catalog",
        data=catalog_snapshot_data,
        event_id=state.event_id,
        params=query_params,
    )
    catalog_link = generate_catering_catalog_link(
        query_params=query_params if query_params else None,
        snapshot_id=catalog_snapshot_id,
    )
    lines.append("")
    lines.append(catalog_link)
    lines.append("")
    lines.append("Menu options you can add:")

    for entry in catering_alternatives:
        name = entry.get("name") or "Catering option"
        unit_price = float(entry.get("unit_price") or 0.0)
        unit_label = (entry.get("unit") or "per event").replace("_", " ")

        menu_snapshot_data = {
            "menu": dict(entry),
            "name": name,
            "room": room,
            "date": link_date,
        }
        menu_snapshot_id = create_snapshot(
            snapshot_type="catering_menu",
            data=menu_snapshot_data,
            event_id=state.event_id,
            params={"menu": name, "room": room, "date": link_date},
        )
        menu_link = generate_catering_menu_link(name, room=room, date=link_date, snapshot_id=menu_snapshot_id)
        lines.append(f"- {name} · CHF {unit_price:,.2f} {unit_label}")
        lines.append(f"  {menu_link}")

    lines.append("")


def _append_product_alternatives(lines: List[str], product_alternatives: List[Dict[str, Any]]) -> None:
    """Append product alternatives section to lines."""
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


def _append_catering_alternatives(lines: List[str], catering_alternatives: List[Dict[str, Any]]) -> None:
    """Append catering alternatives section to lines."""
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


# Backwards compatibility aliases
_compose_offer_summary = compose_offer_summary
_default_menu_alternatives = default_menu_alternatives


__all__ = [
    "compose_offer_summary",
    "default_menu_alternatives",
    "_compose_offer_summary",
    "_default_menu_alternatives",
]
