# backend/workflows/groups/intake/condition.py
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from workflows.conditions.checks import has_event_date as _has_event_date
from workflows.conditions.checks import is_event_request as _is_event_request
from workflows.groups.room_availability.condition import (
    room_status_on_date as _room_status_on_date,
)

__workflow_role__ = "Condition"


def is_event_request(intent: Any) -> bool:
    """[Condition] Determine whether the classified intent corresponds to an event."""

    return _is_event_request(intent)


has_event_date = _has_event_date
has_event_date.__doc__ = """[Condition] Detect if user-provided information includes a valid event date."""


def suggest_dates(
    db: Dict[str, Any],
    preferred_room: str,
    start_from_iso: Any,
    days_ahead: int = 30,
    max_results: int = 5,
) -> List[str]:
    """[Condition] Offer candidate dates for a preferred room when missing."""

    today = date.today()
    start_date = today
    if start_from_iso:
        try:
            start_dt = datetime.fromisoformat(str(start_from_iso).replace("Z", "+00:00"))
            start_date = start_dt.date()
        except ValueError:
            start_date = today
    if start_date < today:
        start_date = today
    suggestions: List[str] = []
    for offset in range(days_ahead):
        day = start_date + timedelta(days=offset)
        day_ddmmyyyy = day.strftime("%d.%m.%Y")
        status = room_status_on_date(db, day_ddmmyyyy, preferred_room)
        if status == "Available":
            suggestions.append(day_ddmmyyyy)
            if len(suggestions) >= max_results:
                break
    return suggestions


room_status_on_date = _room_status_on_date
room_status_on_date.__doc__ = """[Condition] Check existing events on a given date for the same room."""
