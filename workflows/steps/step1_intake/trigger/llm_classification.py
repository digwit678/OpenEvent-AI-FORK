"""LLM classification and entity extraction module.

This module wraps the LLM-based intent classification and entity extraction,
including:
- Intent classification with confidence scoring
- User information extraction (date, participants, room, etc.)
- Room validation (reject false positives like "Room F" from "room for")
- Regex fallback for date extraction when LLM fails
- Confidence boosting for clear event requests

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from domain import IntentLabel
from workflows.common.types import WorkflowState
from workflows.io.database import load_rooms
from workflows.nlu.preferences import extract_preferences
from workflows.common.datetime_parse import parse_first_date
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy

from debug.hooks import trace_entity, trace_marker, trace_prompt_in, trace_prompt_out

from ..llm.analysis import classify_intent, extract_user_information
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from .intent_helpers import (
    needs_vague_date_confirmation as _needs_vague_date_confirmation,
    initial_intent_detail as _initial_intent_detail,
    has_same_turn_shortcut as _has_same_turn_shortcut,
)

logger = logging.getLogger(__name__)


def validate_extracted_room(room_value: Optional[str], message_text: Optional[str] = None) -> Optional[str]:
    """Validate that extracted room matches a known room name exactly (case-insensitive).

    The LLM entity extraction can produce false positives like extracting "Room F"
    from "room for 30 people". This filter:
    1. Ensures the room name exists in the database
    2. Detects false positives from "room <preposition>" patterns

    Args:
        room_value: The room name extracted by LLM
        message_text: Original message text for false positive detection

    Returns:
        The room name if valid, None otherwise
    """
    if not room_value:
        return None

    # Get valid room names from database
    valid_rooms = load_rooms()
    if not valid_rooms:
        return None

    # Case-insensitive exact match against known rooms
    room_lower = room_value.strip().lower()
    canonical_room = None
    for valid_room in valid_rooms:
        if valid_room.lower() == room_lower:
            canonical_room = valid_room
            break

    if not canonical_room:
        return None

    # [FALSE POSITIVE DETECTION] Check if extraction might be from "room <preposition>"
    # Pattern: "room for", "room to", "room in", etc. where LLM extracts "Room F", "Room T", etc.
    if message_text:
        text_lower = message_text.lower()
        prepositions = ["for", "to", "in", "at", "with", "on", "is", "as", "and", "or", "the"]
        # Extract the room suffix (e.g., "F" from "Room F")
        room_suffix = canonical_room.split()[-1].lower() if " " in canonical_room else canonical_room.lower()

        for prep in prepositions:
            pattern = rf"\broom\s+{prep}\b"
            if re.search(pattern, text_lower) and prep.startswith(room_suffix):
                # The extracted room letter matches a preposition - likely false positive
                explicit_room_pattern = rf"\broom\s*{room_suffix}\b"
                if not re.search(explicit_room_pattern, text_lower):
                    logger.debug(
                        "[Step1][ROOM_FALSE_POSITIVE] Detected 'room %s' pattern without explicit room selection",
                        prep,
                    )
                    return None

    return canonical_room


def classify_and_extract(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    owner_step: str,
    thread_id: str,
) -> Tuple[IntentLabel, float, Dict[str, Any], bool]:
    """Classify intent and extract user information from message.

    Performs:
    1. LLM-based intent classification
    2. LLM-based entity extraction
    3. Room validation to reject false positives
    4. Regex fallback for date extraction
    5. Vague date handling (month/weekday hints)
    6. Preference extraction

    Args:
        state: Current workflow state
        message_payload: Raw message data
        owner_step: The owning step for tracing (e.g., "Step1_Intake")
        thread_id: Thread ID for tracing

    Returns:
        Tuple of (intent, confidence, user_info, needs_vague_date_confirmation)
    """
    # Build prompt for classification
    prompt_payload = (
        f"Subject: {message_payload.get('subject') or ''}\n"
        f"Body:\n{message_payload.get('body') or ''}"
    )

    # Classify intent
    trace_prompt_in(thread_id, owner_step, "classify_intent", prompt_payload)
    intent, confidence = classify_intent(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "classify_intent",
        json.dumps({"intent": intent.value, "confidence": round(confidence, 3)}, ensure_ascii=False),
        outputs={"intent": intent.value, "confidence": round(confidence, 3)},
    )
    trace_marker(
        thread_id,
        "AGENT_CLASSIFY",
        detail=intent.value,
        data={"confidence": round(confidence, 3)},
        owner_step=owner_step,
    )
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = _initial_intent_detail(intent)

    # Extract user information
    trace_prompt_in(thread_id, owner_step, "extract_user_information", prompt_payload)
    user_info = extract_user_information(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "extract_user_information",
        json.dumps(user_info, ensure_ascii=False),
        outputs=user_info,
    )

    # [ROOM VALIDATION] Reject false positive room extractions
    if user_info.get("room"):
        original_text = f"{message_payload.get('subject', '')} {message_payload.get('body', '')}".strip()
        validated_room = validate_extracted_room(user_info["room"], message_text=original_text)
        if validated_room != user_info["room"]:
            logger.debug(
                "[Step1][ROOM_VALIDATION] Rejected room extraction: %r -> %r",
                user_info["room"],
                validated_room,
            )
        user_info["room"] = validated_room

    # [REGEX FALLBACK] If LLM failed to extract date, try regex parsing
    if not user_info.get("date") and not user_info.get("event_date"):
        body_text = message_payload.get("body") or ""
        fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
        parsed_date = parse_first_date(body_text, fallback_year=fallback_year)
        if parsed_date:
            user_info["date"] = parsed_date.isoformat()
            user_info["event_date"] = format_iso_date_to_ddmmyyyy(parsed_date.isoformat())
            logger.debug("[Step1] Regex fallback extracted date: %s", parsed_date.isoformat())
            # Boost confidence if we found date via regex - indicates valid event request
            if intent == IntentLabel.EVENT_REQUEST and confidence < 0.90:
                confidence = 0.90
                state.confidence = confidence
                logger.debug("[Step1] Boosted confidence to %s due to regex date extraction", confidence)

    # Check for vague date (month/weekday hints instead of specific date)
    needs_vague = _needs_vague_date_confirmation(user_info)
    if needs_vague:
        user_info.pop("event_date", None)
        user_info.pop("date", None)

    # Extract preferences from raw message text
    raw_pref_text = "\n".join([
        message_payload.get("subject") or "",
        message_payload.get("body") or "",
    ]).strip()
    preferences = extract_preferences(user_info, raw_text=raw_pref_text or None)
    if preferences:
        user_info["preferences"] = preferences

    # Detect same-turn shortcut (room + date + participants all in first message)
    if intent == IntentLabel.EVENT_REQUEST and _has_same_turn_shortcut(user_info):
        state.intent_detail = "event_intake_shortcut"
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")

    return intent, confidence, user_info, needs_vague


def trace_user_entities(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
    owner_step: str,
) -> None:
    """Trace extracted entities for debugging/auditing.

    Args:
        state: Current workflow state
        message_payload: Raw message data
        user_info: Extracted user information
        owner_step: The owning step for tracing
    """
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
    if email:
        trace_entity(thread_id, owner_step, "email", "message_header", True, {"value": email})

    event_date = user_info.get("event_date") or user_info.get("date")
    if event_date:
        trace_entity(thread_id, owner_step, "event_date", "llm", True, {"value": event_date})

    participants = user_info.get("participants") or user_info.get("number_of_participants")
    if participants:
        trace_entity(thread_id, owner_step, "participants", "llm", True, {"value": participants})


def _thread_id(state: WorkflowState) -> str:
    """Get thread ID for tracing."""
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
