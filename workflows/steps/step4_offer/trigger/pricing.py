"""
Step 4 Pricing Input Assembly.

Extracted from step4_handler.py as part of god-file refactoring (Jan 2026).

This module contains:
- rebuild_pricing_inputs: Assemble pricing data from event entry and user overrides

Usage:
    from .pricing import rebuild_pricing_inputs
"""
from __future__ import annotations

from typing import Any, Dict, List

from workflows.common.pricing import derive_room_rate, normalise_rate

from .product_ops import (
    menu_name_set as _menu_name_set,
    normalise_product_fields as _normalise_product_fields,
)


def rebuild_pricing_inputs(
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble pricing inputs from event entry and user overrides.

    This function:
    1. Takes existing pricing_inputs from event_entry
    2. Applies room_rate override if provided in user_info
    3. Derives room rate from catalog if not set
    4. Creates line_items from products
    5. Applies total_amount override if provided in user_info

    Args:
        event_entry: The event database entry
        user_info: User-provided overrides (room_rate, offer_total_override)

    Returns:
        Updated pricing_inputs dict (also written back to event_entry)
    """
    pricing_inputs = dict(event_entry.get("pricing_inputs") or {})
    override_total = user_info.get("offer_total_override")
    menu_names = _menu_name_set()

    # Apply room rate override from user_info
    base_rate_override = normalise_rate(user_info.get("room_rate")) if "room_rate" in user_info else None
    if base_rate_override is not None:
        pricing_inputs["base_rate"] = base_rate_override

    # Derive room rate from catalog if not set
    if normalise_rate(pricing_inputs.get("base_rate")) is None:
        derived_rate = derive_room_rate(event_entry)
        if derived_rate is not None:
            pricing_inputs["base_rate"] = derived_rate

    # Build line items from products
    line_items: List[Dict[str, Any]] = []
    normalised_products: List[Dict[str, Any]] = []
    for product in event_entry.get("products", []):
        normalised = _normalise_product_fields(product, menu_names=menu_names)
        line_items.append(
            {
                "description": normalised["name"],
                "quantity": normalised["quantity"],
                "unit_price": normalised["unit_price"],
                "amount": normalised["quantity"] * normalised["unit_price"],
            }
        )
        normalised_products.append(normalised)

    # Update event_entry with normalised products
    if normalised_products:
        event_entry["products"] = normalised_products

    pricing_inputs["line_items"] = line_items

    # Apply total override if provided
    if override_total is not None:
        try:
            pricing_inputs["total_amount"] = float(override_total)
        except (TypeError, ValueError):
            pricing_inputs.pop("total_amount", None)

    # Write back to event_entry
    event_entry["pricing_inputs"] = pricing_inputs
    return pricing_inputs


# Backwards compatibility alias
_rebuild_pricing_inputs = rebuild_pricing_inputs


__all__ = [
    "rebuild_pricing_inputs",
    "_rebuild_pricing_inputs",
]
