from __future__ import annotations

import json
import hashlib
from typing import Any, Dict


REQUIREMENT_KEYS = [
    "number_of_participants",
    "seating_layout",
    "event_duration",
    "special_requirements",
    "preferred_room",
]


def build_requirements(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """[Condition] Canonicalise requirement-related fields from user info."""

    participants = user_info.get("participants")
    seating_layout = user_info.get("layout") or user_info.get("type")
    event_duration = {
        "start": user_info.get("start_time"),
        "end": user_info.get("end_time"),
    }
    if not event_duration["start"] and not event_duration["end"]:
        event_duration = {}
    special_requirements = user_info.get("notes")
    preferred_room = user_info.get("room")
    requirements = {
        "number_of_participants": participants,
        "seating_layout": seating_layout,
        "event_duration": event_duration,
        "special_requirements": special_requirements,
        "preferred_room": preferred_room,
    }
    return {key: requirements.get(key) for key in REQUIREMENT_KEYS}


def stable_hash(payload: Any) -> str:
    """[Condition] Produce a stable SHA256 hash for arbitrary JSON-serialisable data."""

    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def requirements_hash(requirements: Dict[str, Any]) -> str:
    """[Condition] Hash requirements using canonical order."""

    return stable_hash({key: requirements.get(key) for key in REQUIREMENT_KEYS})
