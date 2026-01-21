"""Room choice detection helper for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from workflows.io.database import load_rooms
from .normalization import normalize_room_token


import logging

logger = logging.getLogger(__name__)


def detect_room_choice(
    message_text: str,
    linked_event: Optional[Dict[str, Any]],
    unified_detection: Optional[Any] = None,
) -> Optional[str]:
    """Detect room selection in message text.

    Note: This function calls load_rooms() to get available rooms.
    Consider refactoring to accept rooms parameter in future.

    Args:
        message_text: The message text to analyze
        linked_event: The linked event entry
        unified_detection: Optional unified detection result from LLM

    Returns:
        Room name if detected, None otherwise.
    """
    if not message_text or not linked_event:
        return None

    # DEBUG: Log detection context
    is_acceptance = getattr(unified_detection, "is_acceptance", False) if unified_detection else False
    logger.debug("[ROOM_DETECT] unified_detection=%s, is_acceptance=%s, msg=%s...",
                 unified_detection is not None, is_acceptance, message_text[:50])

    # -------------------------------------------------------------------------
    # IDEMPOTENCY GUARD: If room is already locked, DON'T detect room choices.
    # A locked room means the client has already confirmed their room selection.
    # Re-mentioning the same room in an acceptance/confirmation message should
    # NOT trigger room choice detection - it's a NO-OP.
    # -------------------------------------------------------------------------
    locked_room = linked_event.get("locked_room_id")
    if locked_room:
        logger.debug("[ROOM_DETECT] IDEMPOTENCY_GUARD: Room already locked (%s), skipping room detection", locked_room)
        return None

    try:
        current_step = int(linked_event.get("current_step") or 0)
    except (TypeError, ValueError):
        current_step = 0
    print(f"[ROOM_DETECT_DEBUG] current_step={current_step}, message={message_text[:50] if message_text else None}")
    if current_step < 3:
        print(f"[ROOM_DETECT_DEBUG] BLOCKED: current_step={current_step} < 3")
        return None
    print(f"[ROOM_DETECT_DEBUG] PROCEEDING with detection")

    rooms = load_rooms()
    if not rooms:
        return None

    text = message_text.strip()
    if not text:
        return None
    lowered = text.lower()

    # -------------------------------------------------------------------------
    # FIX: Question guard - don't lock room if message is a question ABOUT the room
    # "Is Room A available?" should NOT lock Room A
    # BUT "Room B looks perfect. Do you offer catering?" SHOULD lock Room B
    # (the question is unrelated to the room selection)
    # -------------------------------------------------------------------------
    # Split into sentences and check if room mention is in a question sentence
    sentences = re.split(r'[.!]\s*', lowered)
    # Only block if the ENTIRE message is a question or room is in question sentence
    is_pure_question = lowered.strip().endswith("?") and len(sentences) <= 1

    if is_pure_question:
        return None

    # Also check unified detection is_question signal - but only for pure questions
    # Hybrid messages (statement + question) should still detect room from statement part
    if unified_detection and getattr(unified_detection, "is_question", False):
        # Check if there's a non-question sentence with room confirmation
        non_question_parts = [s for s in sentences if "?" not in s and s.strip()]
        if not non_question_parts:
            return None

    # -------------------------------------------------------------------------
    # FIX: Acceptance guard - don't lock room if message is accepting an offer
    # "I accept this offer for Room A" should NOT trigger room choice detection
    # The room is already locked; this is a confirmation, not a new selection.
    # -------------------------------------------------------------------------
    if unified_detection and getattr(unified_detection, "is_acceptance", False):
        logger.debug("[ROOM_DETECT] ACCEPTANCE_GUARD: is_acceptance=True, skipping room detection")
        return None

    # Fallback regex guard for acceptance (when unified detection unavailable)
    acceptance_patterns = [
        r"\bi\s+accept\b", r"\bwe\s+accept\b", r"\baccept\s+(this|the)\s+offer\b",
        r"\bi\s+confirm\b", r"\bwe\s+confirm\b", r"\bconfirm\s+(this|the)\s+offer\b",
        r"\bgo\s+ahead\b", r"\bbook\s+it\b", r"\blet'?s\s+book\b",
    ]
    for pattern in acceptance_patterns:
        if re.search(pattern, lowered):
            logger.debug("[ROOM_DETECT] ACCEPTANCE_GUARD: matched pattern '%s', skipping room detection", pattern)
            return None
    condensed = normalize_room_token(text)

    # direct match against known room labels (with word boundaries to avoid "room for" matching "Room F")
    for room in rooms:
        room_lower = room.lower()
        # Use word boundary regex to avoid "room for" matching "room f"
        room_pattern = rf"\b{re.escape(room_lower)}\b"
        if re.search(room_pattern, lowered):
            logger.info("[ROOM_DETECT] MATCHED room=%s in message (pattern=%s)", room, room_pattern)
            return room
        if normalize_room_token(room) and normalize_room_token(room) == condensed:
            return room

    # pattern like "room a" or "room-a"
    match = re.search(r"\broom\s*([a-z0-9]+)\b", lowered)
    if match:
        token = match.group(1)
        token_norm = normalize_room_token(token)
        for room in rooms:
            room_tokens = room.split()
            if room_tokens:
                last_token = normalize_room_token(room_tokens[-1])
                if token_norm and token_norm == last_token:
                    return room

    # single token equals last token of room name (e.g., "A")
    if len(lowered.split()) == 1:
        token_norm = condensed
        if token_norm:
            for room in rooms:
                last_token = normalize_room_token(room.split()[-1])
                if token_norm == last_token:
                    return room

    return None
