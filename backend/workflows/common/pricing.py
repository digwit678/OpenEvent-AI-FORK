from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from backend.utils import json_io
from backend.workflows.groups.room_availability.db_pers import load_rooms_config

ROOM_RATE_FALLBACKS: Dict[str, float] = {
    "room a": 500.0,
    "room b": 750.0,
    "room c": 1100.0,
    "punkt.null": 1500.0,
}


def normalise_rate(value: Any) -> Optional[float]:
    """Parse a numeric rate and ignore empty/zero values."""

    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return rate


def _room_name_from_event(event_entry: Dict[str, Any]) -> Optional[str]:
    return (
        event_entry.get("locked_room_id")
        or (event_entry.get("room_pending_decision") or {}).get("selected_room")
        or (event_entry.get("requirements") or {}).get("preferred_room")
    )


@lru_cache(maxsize=1)
def _room_rate_map() -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    info_path = Path(__file__).resolve().parents[3] / "room_info.json"
    if info_path.exists():
        try:
            with info_path.open("r", encoding="utf-8") as handle:
                payload = json_io.load(handle)
            for entry in payload.get("rooms") or []:
                name = str(entry.get("name") or "").strip()
                rate = normalise_rate(entry.get("full_day_rate"))
                if name and rate is not None:
                    mapping[name.lower()] = rate
        except Exception:
            # If room info cannot be loaded, fall back to defaults.
            pass

    for key, value in ROOM_RATE_FALLBACKS.items():
        mapping.setdefault(key, value)
    return mapping


@lru_cache(maxsize=1)
def _room_capacity_map() -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for entry in load_rooms_config() or []:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        capacity = (
            entry.get("capacity_max")
            or entry.get("capacity")
            or entry.get("max_capacity")
            or entry.get("capacity_maximum")
        )
        try:
            mapping[name.lower()] = int(capacity)
        except (TypeError, ValueError):
            continue
    return mapping


def _rate_from_capacity(room_name: str) -> Optional[float]:
    capacity = _room_capacity_map().get(room_name.lower())
    if not capacity:
        return None

    multiplier = 12.5 if capacity <= 60 else 13.75
    estimate = math.ceil((capacity * multiplier) / 50.0) * 50.0
    return normalise_rate(estimate)


def room_rate_for_name(room_name: Optional[str]) -> Optional[float]:
    """Return a daily room rate using configured or derived pricing."""

    if not room_name:
        return None
    cleaned = str(room_name).strip()
    if not cleaned:
        return None

    rate_map = _room_rate_map()
    explicit = normalise_rate(rate_map.get(cleaned.lower()))
    if explicit is not None:
        return explicit

    return _rate_from_capacity(cleaned)


def derive_room_rate(event_entry: Dict[str, Any]) -> Optional[float]:
    """Lookup the room rate for the selected/locked room on the event."""

    room_name = _room_name_from_event(event_entry)
    return room_rate_for_name(room_name)

