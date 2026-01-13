"""Room choice detection helper for Step 1.

Extracted from step1_handler.py as part of I1 refactoring (Dec 2025).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from workflows.io.database import load_rooms
from .normalization import normalize_room_token


def detect_room_choice(
    message_text: str, linked_event: Optional[Dict[str, Any]]
) -> Optional[str]:
    """Detect room selection in message text.

    Note: This function calls load_rooms() to get available rooms.
    Consider refactoring to accept rooms parameter in future.

    Returns:
        Room name if detected, None otherwise.
    """
    if not message_text or not linked_event:
        return None
    try:
        current_step = int(linked_event.get("current_step") or 0)
    except (TypeError, ValueError):
        current_step = 0
    if current_step < 3:
        return None

    rooms = load_rooms()
    if not rooms:
        return None

    text = message_text.strip()
    if not text:
        return None
    lowered = text.lower()
    condensed = normalize_room_token(text)

    # direct match against known room labels (with word boundaries to avoid "room for" matching "Room F")
    for room in rooms:
        room_lower = room.lower()
        # Use word boundary regex to avoid "room for" matching "room f"
        room_pattern = rf"\b{re.escape(room_lower)}\b"
        if re.search(room_pattern, lowered):
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
