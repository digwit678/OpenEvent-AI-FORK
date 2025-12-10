"""
Safety Sandwich wiring for workflow integration.

This module provides helper functions to integrate the Safety Sandwich pattern
into workflow steps 3 (room availability) and 4 (offer).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.ux.verbalizer_payloads import (
    RoomFact,
    MenuFact,
    RoomOfferFacts,
    build_room_offer_facts,
)
from backend.llm.verbalizer_agent import verbalize_room_offer

logger = logging.getLogger(__name__)


def verbalize_room_response(
    fallback_text: str,
    *,
    event_date: Optional[str] = None,
    event_date_iso: Optional[str] = None,
    participants_count: Optional[int] = None,
    rooms: Optional[List[Dict[str, Any]]] = None,
    recommended_room: Optional[str] = None,
    locale: str = "en",
) -> str:
    """
    Verbalize a room availability response using the Safety Sandwich pattern.

    Args:
        fallback_text: Deterministic template text to use if verification fails
        event_date: Event date in DD.MM.YYYY format
        event_date_iso: Event date in ISO format
        participants_count: Number of participants
        rooms: List of room data dicts from verbalizer_rooms_payload
        recommended_room: Name of recommended room (first available/option)
        locale: Language locale (en or de)

    Returns:
        Verbalized text (LLM output if verification passes, fallback otherwise)
    """
    if not fallback_text or not fallback_text.strip():
        return fallback_text

    # Build facts from room data
    room_facts: List[RoomFact] = []
    if rooms:
        for room in rooms:
            requirements = room.get("requirements") or {}
            room_fact = RoomFact(
                name=room.get("name") or room.get("id") or "Room",
                status=room.get("status") or "Available",
                capacity_max=room.get("capacity"),
                matched_preferences=requirements.get("matched", []),
                missing_preferences=requirements.get("missing", []),
                hint=room.get("hint"),
            )
            room_facts.append(room_fact)

    # Determine recommended room if not provided
    if not recommended_room and room_facts:
        for rf in room_facts:
            if rf.status in ("Available", "Option"):
                recommended_room = rf.name
                break

    # Build facts bundle
    facts = RoomOfferFacts(
        event_date=event_date or "",
        event_date_iso=event_date_iso,
        participants_count=participants_count,
        rooms=room_facts,
        recommended_room=recommended_room,
        current_step=3,
    )

    # Call the Safety Sandwich verbalizer
    return verbalize_room_offer(facts, fallback_text, locale=locale)


def verbalize_offer_response(
    fallback_text: str,
    *,
    event_date: Optional[str] = None,
    event_date_iso: Optional[str] = None,
    participants_count: Optional[int] = None,
    room_name: Optional[str] = None,
    total_amount: Optional[float] = None,
    deposit_amount: Optional[float] = None,
    products: Optional[List[Dict[str, Any]]] = None,
    locale: str = "en",
) -> str:
    """
    Verbalize an offer response using the Safety Sandwich pattern.

    Args:
        fallback_text: Deterministic template text to use if verification fails
        event_date: Event date in DD.MM.YYYY format
        event_date_iso: Event date in ISO format
        participants_count: Number of participants
        room_name: Name of the selected room
        total_amount: Total amount as numeric value
        deposit_amount: Deposit amount as numeric value
        products: List of product/menu items
        locale: Language locale (en or de)

    Returns:
        Verbalized text (LLM output if verification passes, fallback otherwise)
    """
    if not fallback_text or not fallback_text.strip():
        return fallback_text

    # Build room fact for the selected room
    room_facts: List[RoomFact] = []
    if room_name:
        room_facts.append(RoomFact(name=room_name, status="Option"))

    # Build menu facts from products
    menu_facts: List[MenuFact] = []
    if products:
        for product in products:
            price_val = product.get("unit_price") or product.get("price")
            price_str = ""
            price_numeric = None
            if price_val is not None:
                try:
                    price_numeric = float(price_val)
                    price_str = f"CHF {price_numeric:.2f}"
                except (TypeError, ValueError):
                    price_str = str(price_val)

            menu_fact = MenuFact(
                name=product.get("name") or "Item",
                price=price_str,
                price_numeric=price_numeric,
            )
            menu_facts.append(menu_fact)

    # Format amounts
    total_str = None
    deposit_str = None
    if total_amount is not None:
        total_str = f"CHF {total_amount:.2f}"
    if deposit_amount is not None:
        deposit_str = f"CHF {deposit_amount:.2f}"

    # Build facts bundle
    facts = RoomOfferFacts(
        event_date=event_date or "",
        event_date_iso=event_date_iso,
        participants_count=participants_count,
        rooms=room_facts,
        recommended_room=room_name,
        menus=menu_facts,
        total_amount=total_str,
        total_amount_numeric=total_amount,
        deposit_amount=deposit_str,
        deposit_amount_numeric=deposit_amount,
        current_step=4,
        status="Option",
    )

    # Call the Safety Sandwich verbalizer
    return verbalize_room_offer(facts, fallback_text, locale=locale)


__all__ = [
    "verbalize_room_response",
    "verbalize_offer_response",
]
