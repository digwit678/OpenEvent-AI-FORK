"""
Shared product utilities for workflow steps.

Extracted to workflows/common to avoid circular imports between step4 and step5.
Both steps need these functions for product normalization and pricing.

Usage:
    from workflows.common.product_utils import (
        menu_name_set,
        normalise_product_fields,
    )
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

from workflows.common.menu_options import DINNER_MENU_OPTIONS


def menu_name_set() -> Set[str]:
    """Return set of dinner menu names (lowercase)."""
    return {
        str(entry.get("menu_name") or "").strip().lower()
        for entry in DINNER_MENU_OPTIONS
        if entry.get("menu_name")
    }


def normalise_product_fields(
    product: Dict[str, Any],
    *,
    menu_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Normalize product quantity/unit for pricing and display.

    Args:
        product: Product dict with name, quantity, unit_price, unit fields
        menu_names: Optional set of menu names for unit inference

    Returns:
        Normalized product dict with consistent field types
    """
    menu_names = menu_names or menu_name_set()
    normalised = dict(product)
    name = str(normalised.get("name") or "").strip()
    unit = normalised.get("unit")

    # Infer unit from menu names if not set
    if not unit and name.lower() in menu_names:
        unit = "per_event"

    # Parse quantity with fallback
    try:
        quantity = float(normalised.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1

    # Parse unit_price with fallback
    try:
        unit_price = float(normalised.get("unit_price") or 0.0)
    except (TypeError, ValueError):
        unit_price = 0.0

    # per_event items always have quantity 1
    if unit == "per_event":
        quantity = 1

    normalised["name"] = name or "Unnamed item"
    normalised["unit"] = unit
    normalised["quantity"] = quantity
    normalised["unit_price"] = unit_price
    return normalised


__all__ = ["menu_name_set", "normalise_product_fields"]
