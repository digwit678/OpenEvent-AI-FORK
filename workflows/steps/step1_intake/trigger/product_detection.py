"""
Step 1 Product Detection Functions.

I1 Phase 2: Product detection helpers for intake processing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from workflows.common.menu_options import DINNER_MENU_OPTIONS


def menu_price_value(price: Any) -> Optional[float]:
    """Extract numeric price value from various formats.

    Args:
        price: Price value (can be int, float, or string like "CHF 85")

    Returns:
        Float price value or None
    """
    if price is None:
        return None
    if isinstance(price, (int, float)):
        return float(price)
    try:
        # Handle strings like "CHF 85" or "85.00"
        price_str = str(price).replace("CHF", "").replace("$", "").strip()
        return float(price_str)
    except (TypeError, ValueError):
        return None


def detect_menu_choice(text: str) -> Optional[Dict[str, Any]]:
    """Detect explicit menu selection from message text.

    Matches known menu names from DINNER_MENU_OPTIONS.

    Args:
        text: Message text to analyze

    Returns:
        Dict with menu details if found, None otherwise
    """
    if not text:
        return None

    text_lower = text.lower()

    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "").strip()
        if not name:
            continue

        # Match menu name (case-insensitive, word boundary)
        pattern = rf"\b{re.escape(name.lower())}\b"
        if re.search(pattern, text_lower):
            return {
                "name": name,
                "price": menu_price_value(menu.get("price")),
                "unit": menu.get("unit") or "per_event",
            }

        # Also try matching without "Menu" suffix
        if name.lower().endswith(" menu"):
            short_name = name[:-5].strip()
            pattern = rf"\b{re.escape(short_name.lower())}\b"
            if re.search(pattern, text_lower):
                return {
                    "name": name,
                    "price": menu_price_value(menu.get("price")),
                    "unit": menu.get("unit") or "per_event",
                }

    return None


# Backward-compatible aliases
_menu_price_value = menu_price_value
_detect_menu_choice = detect_menu_choice


__all__ = [
    "menu_price_value",
    "detect_menu_choice",
    "_menu_price_value",
    "_detect_menu_choice",
]
