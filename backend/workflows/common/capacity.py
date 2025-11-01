from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_ROOM_PRIORITY = ("Room A", "Room B", "Room C", "Punkt.Null")
_LAYOUT_ALIAS = {
    "u shape": "u-shape",
    "ushape": "u-shape",
    "theatre": "theater",
    "board room": "boardroom",
    "board-room": "boardroom",
    "banquet style": "banquet",
    "standing reception": "standing",
}
_LAYOUT_PATTERN = re.compile(r"^(?P<label>[^()]+?)(?:\s*\(.*?(\d{1,3}).*?\))?$", re.IGNORECASE)
_CAPACITY_IN_TEXT = re.compile(r"(\d{1,3})\s*(?:people|ppl|participants|guests)", re.IGNORECASE)


def _data_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _room_catalog() -> Dict[str, Dict[str, Any]]:
    """Load the detailed room catalog from disk (memoized)."""

    path = _data_root() / "room_info.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rooms = {}
    for entry in payload.get("rooms", []):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        rooms[name] = entry
    return rooms


def _normalise_layout(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    cleaned = re.sub(r"[\s\-]+", " ", str(label)).strip().lower()
    if not cleaned:
        return None
    return _LAYOUT_ALIAS.get(cleaned, cleaned)


def _layout_capacity(entry: Dict[str, Any], layout: Optional[str]) -> Optional[int]:
    """Extract the maximum supported headcount for a specific layout."""

    if not layout:
        return None
    normalised = _normalise_layout(layout)
    if not normalised:
        return None
    setups: Iterable[str] = entry.get("setup_options") or []
    for raw in setups:
        match = _LAYOUT_PATTERN.match(str(raw).strip())
        if not match:
            continue
        label = _normalise_layout(match.group("label"))
        if label != normalised:
            continue
        capacity_match = _CAPACITY_IN_TEXT.search(raw)
        if capacity_match:
            try:
                return int(capacity_match.group(1))
            except ValueError:
                continue
    return None


def fits_capacity(room_id: str, attendees: Optional[int], layout: Optional[str]) -> bool:
    """
    Return True when the requested configuration fits within the room limits.

    A missing attendee count defaults to True. Layout-specific capacities are preferred
    over general maxima when available.
    """

    if attendees is None:
        return True

    try:
        attendee_count = int(attendees)
    except (TypeError, ValueError):
        return True

    catalog = _room_catalog()
    room = catalog.get(room_id)
    if not room:
        return True

    layout_cap = _layout_capacity(room, layout)
    if layout_cap is not None and attendee_count > layout_cap:
        return False

    capacity_block = room.get("capacity") or {}
    max_cap = capacity_block.get("max")
    if isinstance(max_cap, (int, float)):
        try:
            if attendee_count > int(max_cap):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _room_priority_key(name: str) -> Tuple[int, str]:
    try:
        priority = _ROOM_PRIORITY.index(name)
    except ValueError:
        priority = len(_ROOM_PRIORITY)
    return priority, name


def alternative_rooms(date: Optional[str], attendees: Optional[int], layout: Optional[str]) -> List[Dict[str, Any]]:
    """
    Return a deterministic list of rooms that satisfy the provided requirements.

    The `date` parameter is currently informational; availability checks are handled
    elsewhere in the workflow so we focus on capacity suitability here.
    """

    suggestions: List[Dict[str, Any]] = []
    catalog = _room_catalog()
    for name, entry in catalog.items():
        layout_cap = _layout_capacity(entry, layout)
        cap_block = entry.get("capacity") or {}
        max_cap = cap_block.get("max")
        if attendees is not None and not fits_capacity(name, attendees, layout):
            continue
        suggestions.append(
            {
                "name": name,
                "max": int(max_cap) if isinstance(max_cap, (int, float)) else None,
                "layout_max": layout_cap,
                "features": list(entry.get("features") or []),
            }
        )
    suggestions.sort(key=lambda item: _room_priority_key(item["name"]))
    return suggestions


def layout_capacity(room_id: str, layout: Optional[str]) -> Optional[int]:
    """Expose the maximum capacity for a specific room/layout combination."""

    if not layout:
        return None
    entry = _room_catalog().get(room_id)
    if not entry:
        return None
    return _layout_capacity(entry, layout)


__all__ = ["fits_capacity", "layout_capacity", "alternative_rooms"]
