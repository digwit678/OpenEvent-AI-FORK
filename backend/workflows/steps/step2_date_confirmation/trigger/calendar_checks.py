"""
Calendar availability checks for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D4 refactoring).

Usage:
    from backend.workflows.steps.step2_date_confirmation.trigger.calendar_checks import (
        candidate_is_calendar_free,
        future_fridays_in_may_june,
        maybe_fuzzy_friday_candidates,
    )
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import List, Optional

from backend.services.availability import calendar_free
from backend.workflows.common.datetime_parse import build_window_iso


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
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "candidate_is_calendar_free",
    "future_fridays_in_may_june",
    "maybe_fuzzy_friday_candidates",
    "preferred_room",  # D13b
]
