from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from workflows.conditions.checks import has_event_date as _has_event_date
from workflows.conditions.checks import is_event_request as _is_event_request

__workflow_role__ = "Condition"


def is_event_request(intent: Any) -> bool:
    """[Condition] Determine whether the classified intent corresponds to an event."""

    return _is_event_request(intent)


def has_event_date(user_info: Dict[str, Any]) -> bool:
    """[Condition] Detect if user-provided information includes a valid event date."""

    return _has_event_date(user_info)


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


def room_status_on_date(db: Dict[str, Any], date_ddmmyyyy: str, room_name: str) -> str:
    """[Condition] Check existing events on a given date for the same room."""

    if not room_name or room_name == "Not specified":
        return "Available"
    room_lc = room_name.lower()
    status_found = None
    for event in db.get("events", []):
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        status = (data.get("Status") or "").lower()
        if status == "confirmed":
            return "Confirmed"
        if status in {"option", "lead"}:
            status_found = "Option"
    return status_found or "Available"
