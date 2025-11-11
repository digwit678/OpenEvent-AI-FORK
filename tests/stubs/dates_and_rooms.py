from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Sequence

SUGGESTED_SATURDAYS = ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]

ROOM_LIBRARY: Dict[str, List[Dict[str, Any]]] = {
    "2026-02-07": [
        {
            "id": "R-A",
            "name": "Room A",
            "capacity": 40,
            "matched": ["Long dining table"],
            "missing": ["Background music"],
        },
        {
            "id": "R-D",
            "name": "Room D",
            "capacity": 50,
            "matched": [],
            "missing": ["Long dining table", "Background music"],
        },
    ],
    "2026-02-14": [
        {
            "id": "R-B",
            "name": "Room B",
            "capacity": 32,
            "matched": ["Long dining table", "Background music"],
            "missing": [],
        },
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 28,
            "matched": ["Background music"],
            "missing": ["Long dining table"],
        },
    ],
    "2026-02-21": [
        {
            "id": "R-A",
            "name": "Room A",
            "capacity": 40,
            "matched": ["Long dining table", "Background music"],
            "missing": [],
        },
        {
            "id": "R-B",
            "name": "Room B",
            "capacity": 32,
            "matched": ["Long dining table"],
            "missing": ["Background music"],
        },
    ],
    "2026-02-28": [
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 28,
            "matched": ["Background music"],
            "missing": ["Long dining table"],
        },
        {
            "id": "R-E",
            "name": "Room E",
            "capacity": 60,
            "matched": ["Long dining table"],
            "missing": ["Background music"],
        },
    ],
}


def suggest_dates(window: Dict[str, Any]) -> Sequence[str]:
    """Return deterministic Saturdays in February 2026 for gatekeeping tests."""

    return list(SUGGESTED_SATURDAYS)


def room_status_on_date(date_iso: str, pax: int, requirements: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    """Provide deterministic room availability responses for tests."""

    iso = (date_iso or "")[:10]
    base = ROOM_LIBRARY.get(iso, ROOM_LIBRARY["2026-02-21"])
    rooms = deepcopy(base)
    for room in rooms:
        room.setdefault("matched", [])
        room.setdefault("missing", [])
    return rooms


__all__ = ["room_status_on_date", "suggest_dates"]
