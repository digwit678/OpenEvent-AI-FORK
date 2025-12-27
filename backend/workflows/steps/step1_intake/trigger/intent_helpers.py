"""Pure intent/intake classification helpers for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

from typing import Any, Dict

from backend.domain import IntentLabel


def needs_vague_date_confirmation(user_info: Dict[str, Any]) -> bool:
    """Check if date is vague (month/weekday only, no explicit date)."""
    explicit_date = bool(user_info.get("event_date") or user_info.get("date"))
    vague_tokens = any(
        bool(user_info.get(key))
        for key in ("range_query_detected", "vague_month", "vague_weekday", "vague_time_of_day")
    )
    return vague_tokens and not explicit_date


def initial_intent_detail(intent: IntentLabel) -> str:
    """Map intent to detail string for event creation."""
    if intent == IntentLabel.EVENT_REQUEST:
        return "event_intake"
    if intent == IntentLabel.NON_EVENT:
        return "non_event"
    return intent.value


def has_same_turn_shortcut(user_info: Dict[str, Any]) -> bool:
    """Detect if both participants and date were captured in the same message."""
    participants = user_info.get("participants") or user_info.get("number_of_participants")
    date_value = user_info.get("date") or user_info.get("event_date")
    return bool(participants and date_value)


def resolve_owner_step(step_num: int) -> str:
    """Map step number to step name string."""
    mapping = {
        1: "Step1_Intake",
        2: "Step2_Date",
        3: "Step3_Room",
        4: "Step4_Offer",
        5: "Step5_Negotiation",
        6: "Step6_Transition",
        7: "Step7_Confirmation",
    }
    return mapping.get(step_num, f"Step{step_num}")
