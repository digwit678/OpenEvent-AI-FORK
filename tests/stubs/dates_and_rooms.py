from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Dict, List, Sequence

ROOM_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "R-A",
        "name": "Room A",
        "capacity_max": 40,
        "capacity_min": 12,
        "capacity_by_layout": {"u_shape": 24, "theatre": 40},
        "features": ["projector", "screen"],
        "services": ["coffee service", "water station"],
    },
    {
        "id": "R-B",
        "name": "Room B",
        "capacity_max": 60,
        "capacity_min": 20,
        "capacity_by_layout": {"u_shape": 20, "theatre": 60},
        "features": ["projector", "sound system"],
        "services": ["coffee service"],
    },
    {
        "id": "R-C",
        "name": "Room C",
        "capacity_max": 28,
        "capacity_min": 10,
        "capacity_by_layout": {"workshop": 24},
        "features": ["screen"],
        "services": ["water station"],
    },
    {
        "id": "R-D",
        "name": "Room D",
        "capacity_max": 26,
        "capacity_min": 10,
        "capacity_by_layout": {"boardroom": 16, "workshop": 22},
        "features": ["projector", "screen"],
        "services": ["coffee service"],
    },
    {
        "id": "R-E",
        "name": "Room E",
        "capacity_max": 60,
        "capacity_min": 24,
        "capacity_by_layout": {"workshop": 40, "theatre": 80},
        "features": ["stage", "sound system", "screen"],
        "services": ["coffee service"],
    },
]

SUGGESTED_SATURDAYS = ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]
MAY_THURSDAYS = ["2026-05-07", "2026-05-14", "2026-05-21", "2026-05-28"]

ROOM_LIBRARY: Dict[str, List[Dict[str, Any]]] = {
    "2025-12-10": [
        {
            "id": "R-A",
            "name": "Room A",
            "capacity": 40,
            "matched": ["U-shape setup", "Projector available", "Coffee service"],
            "missing": [],
        },
        {
            "id": "R-B",
            "name": "Room B",
            "capacity": 60,
            "matched": ["Projector available", "Coffee service"],
            "missing": ["U-shape setup (seats 20)"],
        },
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 28,
            "matched": ["Screen"],
            "missing": ["U-shape setup", "Coffee service", "Projector"],
        },
    ],
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
    "2026-05-07": [
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 80,
            "matched": ["Standing reception", "Bar tables", "Sound system"],
            "missing": ["Dedicated catering station"],
        },
        {
            "id": "R-D",
            "name": "Room D",
            "capacity": 70,
            "matched": ["Sound system"],
            "missing": ["Standing reception", "Bar tables"],
        },
    ],
    "2026-05-14": [
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 80,
            "matched": ["Standing reception", "Bar tables", "Sound system"],
            "missing": ["Dedicated catering station"],
        },
        {
            "id": "R-D",
            "name": "Room D",
            "capacity": 70,
            "matched": ["Sound system"],
            "missing": ["Standing reception", "Bar tables"],
        },
    ],
    "2026-05-21": [
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 80,
            "matched": ["Standing reception", "Bar tables", "Sound system"],
            "missing": ["Dedicated catering station"],
        },
        {
            "id": "R-D",
            "name": "Room D",
            "capacity": 70,
            "matched": ["Sound system"],
            "missing": ["Standing reception", "Bar tables"],
        },
    ],
    "2026-05-28": [
        {
            "id": "R-C",
            "name": "Room C",
            "capacity": 80,
            "matched": ["Standing reception", "Bar tables", "Sound system"],
            "missing": ["Dedicated catering station"],
        },
        {
            "id": "R-D",
            "name": "Room D",
            "capacity": 70,
            "matched": ["Sound system"],
            "missing": ["Standing reception", "Bar tables"],
        },
    ],
}


def suggest_dates(*_args: Any, **_kwargs: Any) -> Sequence[str]:
    """Return deterministic date candidates scoped to the expected test windows."""

    start_from_iso = _kwargs.get("start_from_iso") or (_args[1] if len(_args) > 1 else None)
    anchor_month = None
    if isinstance(start_from_iso, str) and len(start_from_iso) >= 7:
        anchor_month = start_from_iso[5:7]
    if anchor_month == "05":
        return list(MAY_THURSDAYS)
    return list(SUGGESTED_SATURDAYS)


def week_window(
    year: int,
    month: int,
    week_index: int,
    *,
    weekdays_hint: Sequence[int] | None = None,
    mon_fri_only: bool = True,
) -> List[str]:
    if year == 2025 and month == 12 and week_index == 2:
        return [
            "2025-12-08",
            "2025-12-09",
            "2025-12-10",
            "2025-12-11",
            "2025-12-12",
        ]
    anchor = date(year, month, 1)
    offset = (7 - anchor.weekday()) % 7
    first_monday = anchor + timedelta(days=offset)
    raw_dates = [
        first_monday + timedelta(days=7 * (week_index - 1) + delta)
        for delta in range(7)
    ]
    filtered: List[str] = []
    for candidate in raw_dates:
        if mon_fri_only and candidate.weekday() >= 5:
            continue
        filtered.append(candidate.isoformat())
    hint_days = sorted({int(day) for day in (weekdays_hint or []) if 1 <= int(day) <= 31})
    if hint_days:
        ordered = [
            cand.isoformat()
            for cand in raw_dates
            if cand.day in hint_days and cand.isoformat() in filtered
        ]
        remaining = [iso for iso in filtered if iso not in ordered]
        return ordered + remaining
    return filtered


def room_status_on_date(date_iso: str, pax: int, requirements: Sequence[str] | None = None) -> List[Dict[str, Any]]:
    """Provide deterministic room availability responses for tests."""

    iso = (date_iso or "")[:10]
    base = ROOM_LIBRARY.get(iso, ROOM_LIBRARY["2026-02-21"])
    rooms = deepcopy(base)
    for room in rooms:
        room.setdefault("matched", [])
        room.setdefault("missing", [])
        config = next((cfg for cfg in ROOM_CONFIG if cfg.get("name") == room.get("name")), {})
        services = {str(item).strip().lower() for item in config.get("services") or []}
        features = {str(item).strip().lower() for item in config.get("features") or []}
        layout_map = config.get("capacity_by_layout") or {}
        layout_capacity = layout_map.get("u_shape") or layout_map.get("u-shape")
        badges = {}
        badges["coffee"] = "✓" if "coffee service" in services else "✗"
        if layout_capacity:
            try:
                badge_capacity = int(layout_capacity)
            except (TypeError, ValueError):
                badge_capacity = None
            if badge_capacity is None or pax is None or badge_capacity >= pax:
                badges["u-shape"] = "✓"
            else:
                badges["u-shape"] = "~"
        else:
            badges["u-shape"] = "✗"
        if "projector" in features:
            badges["projector"] = "✓"
        elif "screen" in features:
            badges["projector"] = "~"
        else:
            badges["projector"] = "✗"
        capacity_value = room.get("capacity")
        try:
            capacity_int = int(capacity_value)
        except (TypeError, ValueError):
            capacity_int = None
        if pax is None or capacity_int is None or capacity_int >= pax:
            badges["capacity"] = "✓"
        else:
            badges["capacity"] = "✗"
        room["badges"] = badges
    return rooms


def load_rooms_config(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    return deepcopy(ROOM_CONFIG)


__all__ = ["room_status_on_date", "suggest_dates", "week_window", "load_rooms_config"]
