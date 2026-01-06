"""
Calendar availability checks for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D4 refactoring).

Usage:
    from workflows.steps.step2_date_confirmation.trigger.calendar_checks import (
        candidate_is_calendar_free,
        future_fridays_in_may_june,
        maybe_fuzzy_friday_candidates,
    )
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import List, Optional

from services.availability import calendar_free
from workflows.common.datetime_parse import build_window_iso
from workflows.io.database import update_event_metadata  # D14a

from .types import ConfirmationWindow  # D14a
from .step2_utils import _to_time  # D14a


# -----------------------------------------------------------------------------
# Room Preference Accessor
# -----------------------------------------------------------------------------


def preferred_room(event_entry: dict) -> str | None:
    """Extract preferred room from event requirements.

    Extracted from step2_handler.py as part of D13b refactoring.

    Args:
        event_entry: Event data dict containing requirements

    Returns:
        Room name if specified, None otherwise
    """
    requirements = event_entry.get("requirements") or {}
    return requirements.get("preferred_room")


# -----------------------------------------------------------------------------
# Calendar Availability
# -----------------------------------------------------------------------------


def candidate_is_calendar_free(
    preferred_room: Optional[str],
    iso_date: str,
    start_time: Optional[time],
    end_time: Optional[time],
) -> bool:
    """
    Check if a room is available on the given date and time window.

    Returns True if:
    - No room preference specified
    - Room preference is "not specified"
    - No time window specified
    - Room is actually free per calendar

    Args:
        preferred_room: Room name to check
        iso_date: ISO date string (YYYY-MM-DD)
        start_time: Start time of the event
        end_time: End time of the event

    Returns:
        True if the slot is available, False otherwise
    """
    if not preferred_room:
        return True
    normalized = preferred_room.strip().lower()
    if not normalized or normalized == "not specified":
        return True
    if not (start_time and end_time):
        return True
    try:
        start_iso, end_iso = build_window_iso(iso_date, start_time, end_time)
    except ValueError:
        return True
    return calendar_free(preferred_room, {"start": start_iso, "end": end_iso})


# -----------------------------------------------------------------------------
# Fuzzy Date Matching
# -----------------------------------------------------------------------------


def future_fridays_in_may_june(anchor: date, count: int = 4) -> List[str]:
    """
    Find future Fridays in May-June period.

    Used for "late spring Friday" fuzzy date matching.

    Args:
        anchor: Reference date (today or later)
        count: Number of Fridays to return

    Returns:
        List of ISO date strings for Fridays in May-June
    """
    results: List[str] = []
    year = anchor.year
    while len(results) < count:
        window_start = date(year, 5, 1)
        window_end = date(year, 6, 30)
        cursor = max(anchor, window_start)
        while cursor <= window_end and len(results) < count:
            if cursor.weekday() == 4 and cursor >= anchor:
                results.append(cursor.isoformat())
            cursor += timedelta(days=1)
        year += 1
    return results[:count]


def maybe_fuzzy_friday_candidates(text: str, anchor: date) -> List[str]:
    """
    Extract fuzzy Friday candidates from text mentioning "late spring Friday".

    Args:
        text: Message text to analyze
        anchor: Reference date for finding future Fridays

    Returns:
        List of ISO date strings if fuzzy match found, empty list otherwise
    """
    lowered = text.lower()
    if "friday" not in lowered:
        return []
    if "late spring" in lowered or ("spring" in lowered and "late" in lowered):
        return future_fridays_in_may_june(anchor)
    return []


# -----------------------------------------------------------------------------
# Calendar Conflict Detection
# -----------------------------------------------------------------------------


def calendar_conflict_reason(event_entry: dict, window: ConfirmationWindow) -> Optional[str]:
    """Check if a calendar conflict exists and return a conflict message.

    Extracted from step2_handler.py as part of D14a refactoring.

    Args:
        event_entry: Event data dict
        window: ConfirmationWindow with date/time info

    Returns:
        Conflict message string if room is booked, None if available.
        Also records the conflict in event_entry if found.
    """
    room = preferred_room(event_entry)
    if not room:
        return None
    normalized = room.strip().lower()
    if not normalized or normalized == "not specified":
        return None
    if not (window.start_time and window.end_time):
        return None
    start_iso = window.start_iso
    end_iso = window.end_iso
    if not (start_iso and end_iso):
        try:
            start_obj = _to_time(window.start_time)
            end_obj = _to_time(window.end_time)
            start_iso, end_iso = build_window_iso(window.iso_date, start_obj, end_obj)
        except ValueError:
            return None
    is_free = calendar_free(room, {"start": start_iso, "end": end_iso})
    if is_free:
        return None
    slot_text = f"{window.start_time}–{window.end_time}"
    conflicts = event_entry.setdefault("calendar_conflicts", [])
    conflict_record = {
        "iso_date": window.iso_date,
        "display_date": window.display_date,
        "start": start_iso,
        "end": end_iso,
        "room": room,
    }
    if conflict_record not in conflicts:
        conflicts.append(conflict_record)
    update_event_metadata(event_entry, calendar_conflicts=conflicts)
    return f"Sorry, {room} is already booked on {window.display_date} ({slot_text}). Let me look for nearby alternatives right away."


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "candidate_is_calendar_free",
    "future_fridays_in_may_june",
    "maybe_fuzzy_friday_candidates",
    "preferred_room",  # D13b
    "calendar_conflict_reason",  # D14a
]
