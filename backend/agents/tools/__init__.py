"""Tool adapters exposed to the OpenAI Agents runtime."""

from __future__ import annotations

from .dates import tool_suggest_dates, tool_persist_confirmed_date, tool_parse_date_intent
from .rooms import (
    tool_evaluate_rooms,
    tool_room_status_on_date,
    tool_capacity_check,
)
from .offer import (
    tool_build_offer_draft,
    tool_persist_offer,
    tool_send_offer,
    tool_list_products,
    tool_list_catering,
    tool_add_product_to_offer,
    tool_remove_product_from_offer,
    tool_follow_up_suggest,
)
from .negotiation import tool_negotiate_offer
from .transition import tool_transition_sync
from .confirmation import tool_classify_confirmation

__all__ = [
    "tool_suggest_dates",
    "tool_persist_confirmed_date",
    "tool_parse_date_intent",
    "tool_evaluate_rooms",
    "tool_room_status_on_date",
    "tool_capacity_check",
    "tool_build_offer_draft",
    "tool_persist_offer",
    "tool_send_offer",
    "tool_list_products",
    "tool_list_catering",
    "tool_add_product_to_offer",
    "tool_remove_product_from_offer",
    "tool_follow_up_suggest",
    "tool_negotiate_offer",
    "tool_transition_sync",
    "tool_classify_confirmation",
]
