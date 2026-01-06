"""Product and menu detection helpers for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from workflows.common.menu_options import DINNER_MENU_OPTIONS


def menu_price_value(raw: Any) -> Optional[float]:
    """Parse price value from various formats like '19.90 CHF'."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        text = str(raw).lower().replace("chf", "").replace(" ", "")
        text = text.replace(",", "").strip()
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def detect_menu_choice(message_text: str) -> Optional[Dict[str, Any]]:
    """Find dinner menu selection in message text.

    Returns:
        Dict with menu details (name, price, unit, month) if found, None otherwise.
    """
    if not message_text:
        return None
    lowered = message_text.lower()
    for menu in DINNER_MENU_OPTIONS:
        name = str(menu.get("menu_name") or "")
        if not name:
            continue
        if name.lower() in lowered:
            price_value = menu_price_value(menu.get("price"))
            return {
                "name": name,
                "price": price_value,
                "unit": "per_event",
                "month": menu.get("available_months"),
            }
    return None
